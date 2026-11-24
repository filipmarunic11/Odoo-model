
import asyncio
import json

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


async def main():

    events = []

    async with async_playwright() as p:

        browser = await p.chromium.launch()
        page = await browser.new_page()

        await page.goto(
            "https://www.club-exil.at/en",
            wait_until="domcontentloaded"
        )

        await page.wait_for_timeout(3000)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        elements = soup.find_all(
            "div",
            class_="event-card__content"
        )

        for element in elements:

            date = element.select_one(".event-card__date")
            title = element.select_one(".event-card__title")

            event = {
                "name": title.get_text(" ", strip=True) if title else "",
                "event_date": date.get_text(" ", strip=True) if date else "",
                "lineup": ""
            }

            events.append(event)

        await browser.close()

    with open("events.json", "w", encoding="utf-8") as file:
        json.dump(events, file, ensure_ascii=False, indent=4)

    print(f"Pronađeno događaja: {len(events)}")
    print("Podaci spremljeni u events.json")

    for event in events:
        print(event)


asyncio.run(main())
