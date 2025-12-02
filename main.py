import os
import datetime as dt
import json
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

# ---- CONFIG ----

API_BASE = "https://screenshotmonitor.com/api/v2"
SSM_TOKEN = os.environ["SSM_TOKEN"]

# Your ScreenshotMonitor employmentId (the one you tested)
TEST_EMPLOYMENT_ID = 433687  # <- change if needed

OUTPUT_DIR = Path("out")


# ---------- HTTP HELPERS ----------

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
    Uses POST /GetScreenshots with an array of activityId GUIDs.
    """
    if not activity_ids:
        print("No activity IDs provided, skipping GetScreenshots.")
        return []

    body = activity_ids

    data = api_post("/GetScreenshots", body)

    if not isinstance(data, list):
        print("Unexpected GetScreenshots response shape, printing raw:")
        print(json.dumps(data, indent=2, default=str))
        return []

    return data


def build_gif_for_employment(
    employment_id: int,
    day: dt.date,
    screenshots: list,
    target_width: int = 1920,          # 1920 ~ 2K, use 1280 for ~1K
    max_frames: int | None = 60,
):
    """
    Download screenshot images at full quality (url), downscale to target_width,
    and build a GIF for a single employment & day.
    Returns the output Path or None if no frames.
    """
    if not screenshots:
        print("No screenshots to build GIF from.")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Sort chronologically by 'taken' timestamp
    screenshots_sorted = sorted(screenshots, key=lambda s: s.get("taken", 0))

    # Optionally limit frames to keep GIF size sane
    if max_frames is not None:
        screenshots_sorted = screenshots_sorted[:max_frames]

    frames = []

    for shot in screenshots_sorted:
        url = shot.get("url")
        shot_id = shot.get("id")

        if not url:
            print(f"Screenshot {shot_id} has no url, skipping.")
            continue

        try:
            print(f"Downloading screenshot {shot_id} from {url}")
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")

            # --- downscale to target_width while preserving aspect ratio ---
            w, h = img.size
            if w > target_width:
                scale = target_width / float(w)
                new_size = (target_width, int(h * scale))
                img = img.resize(new_size, Image.LANCZOS)
                print(f"Resized {shot_id} from {w}x{h} to {new_size[0]}x{new_size[1]}")

            frames.append(img)

        except Exception as e:
            print(f"Failed to download/process screenshot {shot_id}: {e}")

    if not frames:
        print("All screenshot downloads failed – no GIF created.")
        return None

    # Duration per frame in ms
    duration_ms = 800

    out_path = OUTPUT_DIR / f"{employment_id}_{day.isoformat()}.gif"

    print(f"Saving GIF to {out_path} with {len(frames)} frames")
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        format="GIF",
    )

    return out_path



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

    activity_ids = [a["activityId"] for a in activities if "activityId" in a]
    print("\nActivity IDs we will ask screenshots for:")
    print(activity_ids)

    if not activity_ids:
        print("No activities with activityId found – nothing to fetch screenshots for.")
        return

    # 3) Fetch screenshots for these activities
    screenshots = fetch_screenshots_for_activities(activity_ids)
    print(f"\nTotal screenshots returned: {len(screenshots)}")

    print("\n=== Screenshots preview (first 2) ===")
    print(json.dumps(screenshots[:2], indent=2, default=str))

    # 4) Build GIF for this employment & day
    gif_path = build_gif_for_employment(TEST_EMPLOYMENT_ID, day, screenshots, target_width=1280)

    if gif_path:
        print(f"\n✅ GIF created at: {gif_path}")
    else:
        print("\n⚠️ No GIF was created.")


if __name__ == "__main__":
    main()
