import asyncio
import json
from playwright.async_api import async_playwright

COOKIES_FILE = 'cookies.json'

async def save_cookies():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        print("➡️ Navigate to Facebook and log in manually...")
        await page.goto("https://www.facebook.com/")
        print("⏳ Waiting for you to finish login. Close the browser window when you're done.")

        # Wait until user closes browser manually
        await page.wait_for_timeout(30000)
        print("⏱️ Timeout reached, saving cookies...")

        cookies = await context.cookies()
        with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, indent=2)

        await browser.close()
        print(f"✅ Cookies saved to {COOKIES_FILE}")

if __name__ == "__main__":
    asyncio.run(save_cookies())
