import os
import datetime as dt
import json
import requests

# ---- CONFIG ----

# v2 API base
API_BASE = "https://screenshotmonitor.com/api/v2"

# Your X-SSM-Token from GitHub secrets
SSM_TOKEN = os.environ["SSM_TOKEN"]


def api_get(path: str, params: dict | None = None):
    """
    Generic GET for ScreenshotMonitor API v2.
    Auth is only via X-SSM-Token header.
    """
    if params is None:
        params = {}

    url = f"{API_BASE}{path}"

    headers = {
        "X-SSM-Token": SSM_TOKEN,
    }

    print(f"Calling: {url}")
    print(f"With params: {params}")

    resp = requests.get(url, headers=headers, params=params, timeout=60)
    print(f"Status code: {resp.status_code}")

    # 🔴 Instead of raising immediately, dump the body for debugging
    if resp.status_code >= 400:
        print("=== ERROR RESPONSE BODY (first 1000 chars) ===")
        print(resp.text[:1000])
        # Still raise so the workflow is marked as failed
        resp.raise_for_status()

    try:
        return resp.json()
    except Exception:
        print("Response is not JSON. Raw text:")
        print(resp.text[:1000])
        raise

def main():
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    print(f"Testing ScreenshotMonitor API for date: {yesterday}")

    # For now just test GetCommonData, which requires only auth.
    TEST_ENDPOINT = "/GetCommonData"

    params = {}  # no extra params for this one

    data = api_get(TEST_ENDPOINT, params)

    print("\n=== RAW JSON (first 1–2 items) ===")
    if isinstance(data, list):
        preview = data[:2]
    elif isinstance(data, dict) and "data" in data:
        preview = data["data"][:2] if isinstance(data["data"], list) else data
    else:
        preview = data

    print(json.dumps(preview, indent=2, default=str))


if __name__ == "__main__":
    main()
