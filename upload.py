
import json
import requests
import getpass

BASE_URL = "http://localhost:8069/json/2"
DATABASE = "erasmus"
API_KEY = getpass.getpass("Enter your Odoo API key: ")

with open("events.json", "r", encoding="utf-8") as file:
    events = json.load(file)

headers = {
    "Authorization": f"bearer {API_KEY}",
    "Content-Type": "application/json",
    "X-Odoo-Database": DATABASE
}

response = requests.post(
    f"{BASE_URL}/club.event/create",
    headers=headers,
    json={"vals_list": events},
    timeout=30
)

if response.status_code == 200:
    created_ids = response.json()
    print("Events successfully uploaded to Odoo!")
    print("Created record IDs:", created_ids)
    print("Number of uploaded events:", len(events))
else:
    print("Upload failed!")
    print("Status:", response.status_code)
    print("Error:", response.text)
