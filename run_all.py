
import asyncio
import json
import re
import getpass
import requests

from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright


# ODOO POSTAVKE
BASE_URL = "http://localhost:8069/json/2"
DATABASE = "erasmus"
TIMEZONE = "Europe/Vienna"


def to_odoo_datetime(event_date, event_time):
    """Pretvara lokalno vrijeme u UTC za Odoo."""

    local_datetime = datetime.combine(event_date, event_time)
    local_datetime = local_datetime.replace(
        tzinfo=ZoneInfo(TIMEZONE)
    )

    utc_datetime = local_datetime.astimezone(ZoneInfo("UTC"))

    return utc_datetime.strftime("%Y-%m-%d %H:%M:%S")


def extract_times(text, event_name):
    """Pronalazi vrijeme početka i završetka događaja."""

    # Posebno pravilo za 20 Jahre CPE
    if "20 JAHRE CPE" in event_name.upper():
        return "22:00", "00:00"

    # Prvo pokušaj pronaći raspon vremena, npr. 22:00 - 05:00
    range_pattern = (
        r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})"
    )

    match = re.search(range_pattern, text)

    if match:
        return match.group(1), match.group(2)

    # Ako nema raspona, traži vrijeme uz Einlass / Beginn / Start
    start_pattern = (
        r"(?:Einlass|Beginn|Start|Doors|Doors open)"
        r"\s*:?\s*(\d{1,2}:\d{2})"
    )

    match = re.search(start_pattern, text, re.IGNORECASE)

    if match:
        return match.group(1), "00:00"

    # Zadnja mogućnost: pronađi prvo vrijeme u tekstu
    match = re.search(r"\b(\d{1,2}:\d{2})\b", text)

    if match:
        return match.group(1), "00:00"

    return None, None


def parse_event_date(date_text):
    """Pretvara datum sa stranice u Python datum."""

    date_text = date_text.strip().upper()

    return datetime.strptime(
        date_text,
        "%a %d %b %Y"
    ).date()


async def scrape_events():

    events = []

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(
            "https://www.club-exil.at/en",
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(3000)

        buttons = page.locator(
            "div.event-card__content button[data-open-modal]"
        )

        count = await buttons.count()

        print(f"Event cards found: {count}")

        for i in range(count):

            button = buttons.nth(i)

            title_element = button.locator(
                ".event-card__title"
            )

            date_element = button.locator(
                ".event-card__date"
            )

            name = (await title_element.inner_text()).strip()
            date_text = (await date_element.inner_text()).strip()

            print(f"\nReading details: {name}")

            try:
                event_date = parse_event_date(date_text)
            except ValueError:
                print("Could not read event date. Skipping.")
                continue

            await button.click()
            await page.wait_for_timeout(700)

            body_text = await page.locator("body").inner_text()

            # Pronađi tekst nakon naslova događaja
            lower_body = body_text.casefold()
            lower_name = name.casefold()

            position = lower_body.rfind(lower_name)

            if position != -1:
                detail_text = body_text[
                    position + len(name):
                ]
            else:
                detail_text = body_text

            print("\n========== EVENT DETAILS ==========")
            print(detail_text[:2000])
            print("===================================")

            start_time, end_time = extract_times(
                detail_text,
                name
            )

            if not start_time:
                print("No start time found. Skipping:", name)

                # Zatvori modal ako postoji
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)

                continue

            print(
                f"Found time: {start_time} to {end_time}"
            )

            try:
                start_hour, start_minute = map(
                    int, start_time.split(":")
                )

                end_hour, end_minute = map(
                    int, end_time.split(":")
                )

                start_dt = datetime.combine(
                    event_date,
                    time(start_hour, start_minute)
                )

                end_dt = datetime.combine(
                    event_date,
                    time(end_hour, end_minute)
                )

                # Ako završetak nije nakon početka,
                # pomakni ga na sljedeći dan.
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                event = {
                    "name": name,
                    "date_begin": to_odoo_datetime(
                        start_dt.date(),
                        start_dt.time()
                    ),
                    "date_end": to_odoo_datetime(
                        end_dt.date(),
                        end_dt.time()
                    ),
                    "date_tz": TIMEZONE,
                    "seats_limited": False,
                    "badge_format": "A6",
                    "website_visibility": "public"
                }

                events.append(event)

            except ValueError:
                print("Invalid time format. Skipping:", name)

            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

        await browser.close()

    return events


def upload_events(events):

    api_key = getpass.getpass(
        "Enter your Odoo API key: "
    )

    headers = {
        "Authorization": f"bearer {api_key}",
        "Content-Type": "application/json",
        "X-Odoo-Database": DATABASE
    }

    new_count = 0
    updated_count = 0
    failed_count = 0

    for event in events:

        print(f"\nChecking: {event['name']}")

        try:
            # Provjeri postoji li događaj s istim imenom
            search_response = requests.post(
                f"{BASE_URL}/event.event/search_read",
                headers=headers,
                json={
                    "domain": [
                        ["name", "=", event["name"]]
                    ],
                    "fields": ["id"],
                    "limit": 1
                },
                timeout=30
            )

            search_response.raise_for_status()

            existing = search_response.json()

            if existing:

                event_id = existing[0]["id"]

                response = requests.post(
                    f"{BASE_URL}/event.event/write",
                    headers=headers,
                    json={
                        "ids": [event_id],
                        "vals": event
                    },
                    timeout=30
                )

                response.raise_for_status()

                print("Updated:", event["name"])
                print("Odoo ID:", event_id)

                updated_count += 1

            else:

                response = requests.post(
                    f"{BASE_URL}/event.event/create",
                    headers=headers,
                    json={
                        "vals_list": [event]
                    },
                    timeout=30
                )

                response.raise_for_status()

                created_ids = response.json()

                print("Created:", event["name"])
                print("Odoo ID:", created_ids)

                new_count += 1

        except requests.RequestException as error:

            print("Upload failed:", event["name"])
            print(error)

            failed_count += 1

    print("\n========== RESULTS ==========")
    print("New events:", new_count)
    print("Updated events:", updated_count)
    print("Failed:", failed_count)
    print("=============================")


async def main():

    print("Starting Club Exil scraper...\n")

    events = await scrape_events()

    print(
        f"\nEvents with readable start times: {len(events)}"
    )

    with open(
        "events.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            events,
            file,
            ensure_ascii=False,
            indent=4
        )

    print("Events saved to events.json")

    if events:
        upload_events(events)
    else:
        print("No events to upload.")

    print("\nProcess finished!")


asyncio.run(main())
