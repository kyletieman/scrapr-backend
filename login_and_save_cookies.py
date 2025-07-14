from playwright.sync_api import sync_playwright
import json

COOKIE_FILE = "cookies.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    print("Opening Facebook. Please log in manually.")
    page.goto("https://www.facebook.com")

    input("Press ENTER after you've logged in and the page is fully loaded...")

    # Save cookies
    cookies = context.cookies()
    with open(COOKIE_FILE, "w") as f:
        json.dump(cookies, f)

    print("Cookies saved to", COOKIE_FILE)
    browser.close()

