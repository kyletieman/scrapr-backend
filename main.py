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
    user_id = "demo_user_id"
    user_tier = "free"

    keywords_list = [
        line.strip().lower()
        for line in (await keywords.read()).decode("utf-8").splitlines()
        if line.strip()
    ]

    import csv

    groups_content = await groups.read()
    decoded_groups = groups_content.decode("utf-8").strip()

    if decoded_groups.startswith("["):  # assume it's JSON
        groups_list = json.loads(decoded_groups)
    else:  # assume it's CSV or newline text
        groups_list = [
            row[0] for row in csv.reader(decoded_groups.splitlines()) if row and row[0].strip()
        ]

    zip_codes_list = json.loads(zip_codes) if zip_codes else []

    scrape_id = str(uuid.uuid4())

    cookies_content = await cookies.read()
    cookies_path = f"/tmp/cookies_{scrape_id}.json"
    with open(cookies_path, 'wb') as f:
        f.write(cookies_content)

    profile_data = {
        'id': scrape_id,
        'type': type,
        'keywords': keywords_list,
        'groups': groups_list if type == 'group' else None,
        'zip_codes': zip_codes_list if type == 'marketplace' else None,
    }

    session = ScrapingSession(scrape_id, user_id, scrape_id)
    session.profile_data = profile_data
    active_sessions[scrape_id] = session

    asyncio.create_task(run_scraping_job(scrape_id))

    return {"scrape_id": scrape_id}