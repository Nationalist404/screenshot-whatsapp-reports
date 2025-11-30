import os
import datetime as dt
import json
import requests

# ---- CONFIG ----

API_BASE = "https://screenshotmonitor.com/api/v2"
SSM_TOKEN = os.environ["SSM_TOKEN"]

# Replace this with YOUR real employmentId (an integer)
TEST_EMPLOYMENT_ID = 433687  # <--- TODO: put your own id here


def api_get(path: str, params: dict | None = None):
    if params is None:
        params = {}

    url = f"{API_BASE}{path}"
    headers = {"X-SSM-Token": SSM_TOKEN}

    print(f"GET {url}")
    print(f"Params: {params}")

    resp = requests.get(url, headers=headers, params=params, timeout=60)
    print(f"Status code: {resp.status_code}")

    if resp.status_code >= 400:
        print("=== ERROR RESPONSE BODY (first 1000 chars) ===")
        print(resp.text[:1000])
        resp.raise_for_status()

    try:
        return resp.json()
    except Exception:
        print("Response is not JSON. Raw text:")
        print(resp.text[:1000])
        raise


def api_post(path: str, body):
    """
    Generic POST for ScreenshotMonitor API v2.
    Sends X-SSM-Token header + JSON body.
    """
    url = f"{API_BASE}{path}"
    headers = {
        "X-SSM-Token": SSM_TOKEN,
        "Content-Type": "application/json",
    }

    print(f"POST {url}")
    print("Body:")
    print(json.dumps(body, indent=2))

    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print(f"Status code: {resp.status_code}")

    if resp.status_code >= 400:
        print("=== ERROR RESPONSE BODY (first 1000 chars) ===")
        print(resp.text[:1000])
        resp.raise_for_status()

    try:
        return resp.json()
    except Exception:
        print("Response is not JSON. Raw text:")
        print(resp.text[:1000])
        raise


def to_unix_seconds(dt_obj: dt.datetime) -> int:
    """
    Convert a timezone-aware datetime to seconds since 1970-01-01T00:00:00Z.
    """
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return int((dt_obj - epoch).total_seconds())


def main():
    # We'll fetch activities for "yesterday" in UTC
    today = dt.datetime.now(dt.timezone.utc).date()
    yesterday = today - dt.timedelta(days=1)
    print(f"Testing GetActivities for date: {yesterday}")

    start_dt = dt.datetime.combine(yesterday, dt.time(0, 0), tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(today, dt.time(0, 0), tzinfo=dt.timezone.utc)

    from_ts = to_unix_seconds(start_dt)
    to_ts = to_unix_seconds(end_dt)

    print(f"From (unix): {from_ts}")
    print(f"To   (unix): {to_ts}")

    # According to docs, GetActivities expects an array of ranges.
    # We'll send just ONE range for now.
    body = [
        {
            "employmentId": TEST_EMPLOYMENT_ID,
            "from": from_ts,
            "to": to_ts,
        }
    ]

    # Call POST /api/v2/GetActivities
    data = api_post("/GetActivities", body)

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
