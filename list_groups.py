import os
import requests
import json

PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
TOKEN = os.getenv("WHATSAPP_TOKEN")

if not PHONE_ID or not TOKEN:
    raise SystemExit("Missing WHATSAPP_PHONE_ID or WHATSAPP_TOKEN")

url = f"https://graph.facebook.com/v21.0/{PHONE_ID}/groups"

headers = {
    "Authorization": f"Bearer {TOKEN}",
}

print("GET", url)
resp = requests.get(url, headers=headers, timeout=60)
print("Status:", resp.status_code)

# Raw JSON for debugging
print("Raw response:")
print(resp.text)

try:
    data = resp.json()
except Exception as e:
    print("Could not parse JSON:", e)
    raise SystemExit(1)

print("\n=== Groups found ===")
for g in data.get("data", []):
    gid = g.get("id")
    # sometimes it's "subject", sometimes "name"
    name = g.get("subject") or g.get("name")
    print(f"- ID: {gid}\n  Name: {name}\n")
