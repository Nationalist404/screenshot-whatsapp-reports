import os
import datetime as dt
import json
import requests

# ---- CONFIG ----

API_BASE = "https://screenshotmonitor.com/api/v2"
SSM_TOKEN = os.environ["SSM_TOKEN"]

# TODO: if you track multiple people later, we’ll make this a list.
TEST_EMPLOYMENT_ID = 433687  # <--- keep your working id here


# ---------- HTTP HELPERS ----------

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


# ---------- TIME HELPERS ----------

def to_unix_seconds(dt_obj: dt.datetime) -> int:
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return int((dt_obj - epoch).total_seconds())


def get_yesterday_range_utc():
    today = dt.datetime.now(dt.timezone.utc).date()
    yesterday = today - dt.timedelta(days=1)

    start_dt = dt.datetime.combine(yesterday, dt.time(0, 0), tzinfo=dt.timezone.utc)
    end_dt = dt.datetime.combine(today, dt.time(0, 0), tzinfo=dt.timezone.utc)

    return yesterday, to_unix_seconds(start_dt), to_unix_seconds(end_dt)


# ---------- BUSINESS LOGIC ----------

def fetch_activities_for_employment(employment_id: int, from_ts: int, to_ts: int):
    """
    Uses POST /GetActivities with a single range for one employmentId.
    """
    body = [
        {
            "employmentId": employment_id,
            "from": from_ts,
            "to": to_ts,
        }
    ]

    data = api_post("/GetActivities", body)

    if not isinstance(data, list):
        print("Unexpected GetActivities response shape, printing raw:")
        print(json.dumps(data, indent=2, default=str))
        return []

    return data


def fetch_screenshots_for_activities(activity_ids: list[str]):
    """
    Uses POST /GetScreenshots.
    Docs say “Returns screenshots for given activity IDs”.
    Most likely this expects a JSON array of activityId strings.
    If your API docs show a different body shape (e.g. {\"activityIds\": [...]})
    you can adjust 'body' below accordingly.
    """
    if not activity_ids:
        print("No activity IDs provided, skipping GetScreenshots.")
        return []

    # If the docs show a different body form, tweak this:
    body = activity_ids

    data = api_post("/GetScreenshots", body)

    if not isinstance(data, list):
        print("Unexpected GetScreenshots response shape, printing raw:")
        print(json.dumps(data, indent=2, default=str))
        return []

    return data


def main():
    # 1) Figure out yesterday’s unix range
    day, from_ts, to_ts = get_yesterday_range_utc()
    print(f"Fetching activities for date: {day}")
    print(f"From (unix): {from_ts}")
    print(f"To   (unix): {to_ts}")

    # 2) Get activities for this employment
    activities = fetch_activities_for_employment(TEST_EMPLOYMENT_ID, from_ts, to_ts)
    print(f"Total activities returned: {len(activities)}")

    print("\n=== Activities preview (first 2) ===")
    print(json.dumps(activities[:2], indent=2, default=str))

    # 3) Collect a few activityIds
    activity_ids = [a["activityId"] for a in activities if "activityId" in a]

    # Limit just to avoid huge test output
    activity_ids = activity_ids[:10]

    print("\nActivity IDs we will ask screenshots for:")
    print(activity_ids)

    if not activity_ids:
        print("No activities with activityId found – nothing to fetch screenshots for.")
        return

    # 4) Fetch screenshots for these activityIds
    screenshots = fetch_screenshots_for_activities(activity_ids)
    print(f"\nTotal screenshots returned: {len(screenshots)}")

    print("\n=== Screenshots preview (first 2) ===")
    print(json.dumps(screenshots[:2], indent=2, default=str))


if __name__ == "__main__":
    main()
