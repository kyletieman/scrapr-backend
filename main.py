from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import uuid
import os
from datetime import datetime
import csv

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active sessions store
active_sessions = {}

class ScrapingSession:
    def __init__(self, scrape_id: str, user_id: str, profile_id: str):
        self.scrape_id = scrape_id
        self.user_id = user_id
        self.profile_id = profile_id
        self.status = "pending"
        self.results = []
        self.error_message = None
        self.profile_data = {}

async def run_scraping_job(scrape_id: str):
    session = active_sessions.get(scrape_id)
    if not session:
        return
    session.status = "running"
    await asyncio.sleep(3)  # simulate work
    session.results = [{"test": "done"}]
    session.status = "completed"

@app.post("/api/scrape/start")
async def start_scrape(
    type: str = Form(...),
    keywords: UploadFile = File(...),
    groups: UploadFile = File(...),
    zip_codes: str = Form(""),
    cookies: UploadFile = File(...),
    authorization: str = None
):
    user_id = "demo_user_id"
    user_tier = "free"

    # Parse keywords
    keywords_list = [
        line.strip().lower()
        for line in (await keywords.read()).decode("utf-8").splitlines()
        if line.strip()
    ]

    # Parse groups (CSV or JSON)
    groups_content = await groups.read()
    decoded_groups = groups_content.decode("utf-8").strip()

    if decoded_groups.startswith("["):
        try:
            groups_list = json.loads(decoded_groups)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in groups file.")
    else:
        groups_list = [
            row[0] for row in csv.reader(decoded_groups.splitlines()) if row and row[0].strip()
        ]

    # Parse zip codes
    try:
        zip_codes_list = json.loads(zip_codes) if zip_codes else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON for zip_codes.")

    # Store cookies
    scrape_id = str(uuid.uuid4())
    cookies_content = await cookies.read()
    cookies_path = f"/tmp/cookies_{scrape_id}.json"
    with open(cookies_path, "wb") as f:
        f.write(cookies_content)

    # Store session
    profile_data = {
        "id": scrape_id,
        "type": type,
        "keywords": keywords_list,
        "groups": groups_list if type == "group" else None,
        "zip_codes": zip_codes_list if type == "marketplace" else None,
    }

    session = ScrapingSession(scrape_id, user_id, scrape_id)
    session.profile_data = profile_data
    active_sessions[scrape_id] = session

    asyncio.create_task(run_scraping_job(scrape_id))

    return {"scrape_id": scrape_id}

@app.get("/api/scrape/status/{scrape_id}")
async def get_scrape_status(scrape_id: str):
    session = active_sessions.get(scrape_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scrape job not found")
    return {
        "id": scrape_id,
        "status": session.status,
        "results": session.results,
        "error_message": session.error_message
    }

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}