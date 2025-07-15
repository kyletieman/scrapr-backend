from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import uuid
import os
from datetime import datetime, timedelta
from typing import Optional
import stripe
from supabase import create_client, Client
from playwright.async_api import async_playwright
import csv
import io
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Facebook Scraper API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://localhost:3000", 
        "http://127.0.0.1:5173",
        "https://aiscrapr.com",
        "https://www.aiscrapr.com",
        "https://*.vercel.app"  # For preview deployments
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Store active scraping sessions
active_sessions = {}

class ScrapingSession:
    def __init__(self, scrape_id: str, user_id: str, profile_id: str):
        self.scrape_id = scrape_id
        self.user_id = user_id
        self.profile_id = profile_id
        self.status = "pending"
        self.results = []
        self.error_message = None

async def get_user_from_token(authorization: str = None):
    """Extract user from JWT token"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    token = authorization.split(" ")[1]
    try:
        user = supabase.auth.get_user(token)
        return user.user
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")

async def check_usage_limits(user_id: str, user_tier: str):
    """Check if user has exceeded their usage limits"""
    today = datetime.now().date()
    
    # Get user's daily usage
    result = supabase.table('users').select('daily_scrapes_used, last_scrape_date').eq('id', user_id).single().execute()
    user_data = result.data
    
    if user_data['last_scrape_date']:
        last_scrape = datetime.fromisoformat(user_data['last_scrape_date']).date()
        if last_scrape != today:
            # Reset daily counter
            supabase.table('users').update({
                'daily_scrapes_used': 0,
                'last_scrape_date': today.isoformat()
            }).eq('id', user_id).execute()
            user_data['daily_scrapes_used'] = 0
    
    # Check limits based on tier
    if user_tier == 'free' and user_data['daily_scrapes_used'] >= 1:
        raise HTTPException(status_code=429, detail="Daily scrape limit reached")
    
    return True

async def scrape_facebook_groups(page, group_urls, keywords, max_posts=75):
    """Scrape Facebook groups for keywords"""
    results = []
    
    for group_url in group_urls:
        try:
            await page.goto(group_url)
            await page.wait_for_timeout(5000)
            
            # Try to click Discussion tab
            try:
                await page.click("text=Discussion", timeout=5000)
                await page.wait_for_timeout(3000)
            except:
                pass
            
            post_selector = "div[role='feed'] > div"
            seen = set()
            
            for _ in range(30):  # Scroll iterations
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1500)
                
                posts = await page.query_selector_all(post_selector)
                for post in posts:
                    try:
                        text_nodes = await post.query_selector_all('div[dir="auto"]')
                        content = ' '.join([
                            (await node.inner_text()).strip() for node in text_nodes
                        ])
                        
                        if not content or content in seen:
                            continue
                        
                        seen.add(content)
                        content_lower = content.lower()
                        matches = [kw for kw in keywords if kw.lower() in content_lower]
                        
                        if matches:
                            # Find post URL
                            post_url = ""
                            link_tags = await post.query_selector_all('a[href]')
                            for tag in link_tags:
                                href = await tag.get_attribute('href')
                                if href and any(x in href for x in ["/permalink/", "/posts/", "?comment_id=", "/groups/"]):
                                    post_url = href if href.startswith("http") else f"https://facebook.com{href}"
                                    break
                            
                            results.append({
                                'Group URL': group_url,
                                'Post Text (Preview)': content[:200],
                                'Matched Keyword(s)': ', '.join(matches),
                                'Post Link': post_url,
                                'Scraped At': datetime.now().isoformat()
                            })
                    except Exception as e:
                        continue
                
                if len(seen) >= max_posts:
                    break
                    
        except Exception as e:
            print(f"Error scraping group {group_url}: {e}")
            continue
    
    return results

async def scrape_facebook_marketplace(page, zip_codes, keywords):
    """Scrape Facebook Marketplace for keywords"""
    results = []
    
    for zip_code in zip_codes:
        for keyword in keywords:
            try:
                search_url = f"https://www.facebook.com/marketplace/{zip_code}/search/?query={keyword}&exact=false"
                await page.goto(search_url)
                await page.wait_for_timeout(5000)
                
                # Scroll to load more items
                for _ in range(20):
                    await page.mouse.wheel(0, 3000)
                    await page.wait_for_timeout(1500)
                
                items = await page.query_selector_all("a[href*='/marketplace/item/']")
                
                for item in items:
                    try:
                        link = await item.get_attribute("href")
                        if not link:
                            continue
                        
                        if "facebook.com" not in link:
                            link = f"https://www.facebook.com{link}"
                        
                        title = await item.inner_text()
                        title = title.strip().replace("\n", " ")[:100]
                        
                        results.append({
                            'ZIP Code': zip_code,
                            'Keyword': keyword,
                            'Title': title,
                            'URL': link,
                            'Scraped At': datetime.now().isoformat()
                        })
                        
                    except Exception:
                        continue
                        
            except Exception as e:
                print(f"Error scraping marketplace {zip_code} - {keyword}: {e}")
                continue
    
    return results

async def run_scraping_job(scrape_id: str):
    """Run the actual scraping job"""
    session = active_sessions.get(scrape_id)
    if not session:
        return
    
    try:
        session.status = "running"
        
        # Update status in database
        print(f"Starting scrape job {scrape_id}")
        
        # Get profile data from session
        profile = session.profile_data
        
        # Get cookies from uploaded file (stored temporarily)
        cookies_path = f"/tmp/cookies_{scrape_id}.json"
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            
            # Load cookies
            with open(cookies_path, 'r') as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            
            page = await context.new_page()
            
            # Run appropriate scraper
            if profile['type'] == 'group':
                results = await scrape_facebook_groups(
                    page, 
                    profile['groups'], 
                    profile['keywords']
                )
            else:  # marketplace
                results = await scrape_facebook_marketplace(
                    page, 
                    profile['zip_codes'], 
                    profile['keywords']
                )
            
            await browser.close()
        
        # Clean up cookies file
        if os.path.exists(cookies_path):
            os.remove(cookies_path)
        
        session.results = results
        session.status = "completed"
        
        print(f"Scrape job {scrape_id} completed with {len(results)} results")
        
    except Exception as e:
        print(f"Scrape job {scrape_id} failed: {str(e)}")
        session.status = "failed"
        session.error_message = str(e)
        
        # Update database
        supabase.table('scrape_results').update({
            'status': 'failed',
            'error_message': str(e)
        }).eq('id', scrape_id).execute()


@app.get("/api/health")
async def health_check():
    """Health check endpoint for Railway"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

from fastapi import UploadFile, File, Form

@app.post("/api/scrape/start")
async def start_scrape(
    type: str = Form(...),
    keywords: UploadFile = File(...),
    groups: UploadFile = File(...),
    zip_codes: str = Form(""),
    cookies: UploadFile = File(...),
    authorization: str = None
):
    """Start a new scraping job"""
    # For development, use a demo user
    user_id = "demo_user_id"
    user_tier = "free"  # This should come from user data
    
    # Parse the form data
    keywords_list = [
    line.strip().lower()
    for line in (await keywords.read()).decode("utf-8").splitlines()
    if line.strip()
]

    groups_content = await groups.read()
if groups_content:
    groups_list = json.loads(groups_content.decode("utf-8"))
else:
    groups_list = []

    zip_codes_list = json.loads(zip_codes) if zip_codes else []
    
    # Generate scrape ID
    scrape_id = str(uuid.uuid4())
    
    # Save cookies temporarily
    cookies_content = await cookies.read()
    cookies_path = f"/tmp/cookies_{scrape_id}.json"
    with open(cookies_path, 'wb') as f:
        f.write(cookies_content)
    
    # Create a temporary profile for this scrape
    profile_data = {
        'id': scrape_id,  # Use scrape_id as profile_id for simplicity
        'type': type,
        'keywords': keywords_list,
        'groups': groups_list if type == 'group' else None,
        'zip_codes': zip_codes_list if type == 'marketplace' else None,
    }
    
    # Create session
    session = ScrapingSession(scrape_id, user_id, scrape_id)
    session.profile_data = profile_data  # Store profile data in session
    active_sessions[scrape_id] = session
    
    # Start scraping job in background
    asyncio.create_task(run_scraping_job(scrape_id))
    
    return {"scrape_id": scrape_id}

@app.get("/api/scrape/status/{scrape_id}")
async def get_scrape_status(scrape_id: str):
    """Get the status of a scraping job"""
    session = active_sessions.get(scrape_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    
    return {
        "id": scrape_id,
        "status": session.status,
        "results_count": len(session.results) if session.results else 0,
        "error_message": session.error_message,
        "results_data": session.results if session.status == "completed" else None
    }

@app.post("/api/create-checkout-session")
async def create_checkout_session(request: dict):
    """Create Stripe checkout session"""
    plan_id = request.get('plan_id')
    
    # Define price IDs for each plan (these would be created in Stripe dashboard)
    price_ids = {
        'monthly': 'price_monthly_pro',  # Replace with actual Stripe price ID
        'semi_annual': 'price_semi_annual_pro',  # Replace with actual Stripe price ID
        'annual': 'price_annual_pro',  # Replace with actual Stripe price ID
    }
    
    if plan_id not in price_ids:
        raise HTTPException(status_code=400, detail="Invalid plan ID")
    
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_ids[plan_id],
                'quantity': 1,
            }],
            mode='subscription',
            success_url='http://localhost:3000/success',  # Configure for your domain
            cancel_url='http://localhost:3000/cancel',
        )
        
        return {"sessionId": checkout_session.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/create-portal-session")
async def create_portal_session():
    """Create Stripe customer portal session"""
    # In real implementation, get customer ID from user data
    customer_id = "cus_placeholder"  # This should come from user's Stripe customer ID
    
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url='http://localhost:3000/dashboard',  # Configure for your domain
        )
        
        return {"url": portal_session.url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)