
from playwright.sync_api import sync_playwright
import json
import csv
import time
from datetime import datetime

COOKIE_FILE = "cookies.json"
KEYWORDS = ["land for sale", "Lot"]
ZIP_CODES = [
    "75147", "76645", "75701", "75092"
]

def load_cookies(context):
    with open(COOKIE_FILE, "r") as f:
        cookies = json.load(f)
        context.add_cookies(cookies)

def main():
    listings = {}
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_file = f"marketplace_listings_{timestamp}.csv"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        load_cookies(context)
        page = context.new_page()

        for zip_code in ZIP_CODES:
            for keyword in KEYWORDS:
                search_url = f"https://www.facebook.com/marketplace/{zip_code}/search/?query={keyword}&exact=false"
                print(f"Searching: {search_url}")
                page.goto(search_url)
                time.sleep(5)

                scroll_count = 0
                while scroll_count < 20:
                    page.mouse.wheel(0, 3000)
                    time.sleep(1.5)
                    scroll_count += 1

                items = page.locator("a[href*='/marketplace/item/']").all()
                print(f"Found {len(items)} links for {zip_code} - {keyword}")

                for item in items:
                    try:
                        link = item.get_attribute("href")
                        if not link:
                            continue
                        if "facebook.com" not in link:
                            link = "https://www.facebook.com" + link

                        if link in listings:
                            continue

                        title = item.inner_text().strip().replace("\n", " ")

                        listings[link] = {
                            "ZIP Code": zip_code,
                            "Keyword": keyword,
                            "Title": title[:100],
                            "URL": link
                        }
                    except Exception:
                        continue

        browser.close()

    with open(output_file, mode="w", newline="", encoding="utf-8") as file:
        fieldnames = ["ZIP Code", "Keyword", "Title", "URL"]
        writer = csv.DictWriter(file, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for row in listings.values():
            writer.writerow(row)

    print(f"✅ Exported {len(listings)} unique listings to {output_file}")

if __name__ == "__main__":
    main()
