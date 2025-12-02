import os
import datetime as dt
import json
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import imageio.v2 as imageio

# ---- CONFIG: ScreenshotMonitor ----

API_BASE = "https://screenshotmonitor.com/api/v2"
SSM_TOKEN = os.environ["SSM_TOKEN"]

# Map employmentId -> employee name (add more IDs here later)
EMPLOYMENTS = {
    433687: "VOID",   # <--- change/add as needed
}

OUTPUT_DIR = Path("out")

# ---- CONFIG: WhatsApp Cloud API (from GitHub secrets) ----

WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
WHATSAPP_TO_NUMBER = os.environ.get("WHATSAPP_TO_NUMBER")
WHATSAPP_BASE = "https://graph.facebook.com/v22.0"  # adjust version if Meta UI shows different


# ---------- HTTP HELPER FOR SCREENSHOTMONITOR ----------

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


def format_utc_timestamp(ts: int) -> str:
    """Convert unix seconds to readable UTC time string."""
    return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------- SCREENSHOTMONITOR BUSINESS LOGIC ----------

def fetch_activities_for_employment(employment_id: int, from_ts: int, to_ts: int):
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


# ---------- DRAWING / VIDEO BUILDING ----------

def annotate_frame(
    img: Image.Image,
    employee_name: str,
    time_str: str,
    note: str,
    activity_level: int | None,
    app_name: str | None,
):
    """
    Draw a black bar at the bottom of the frame with:
      line 1: employee | time
      line 2: activity level | app
      line 3: note
    """
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    if activity_level is None:
        activity_level = 0
    if app_name is None or app_name == "":
        app_name = "unknown"

    max_note_len = 80
    if note is None:
        note = ""
    if len(note) > max_note_len:
        note = note[: max_note_len - 3] + "..."

    line1 = f"{employee_name} | {time_str}"
    line2 = f"Activity: {activity_level}% | App: {app_name}"
    line3 = f"Note: {note}" if note else ""

    if line3:
        text = f"{line1}\n{line2}\n{line3}"
    else:
        text = f"{line1}\n{line2}"

    bbox = draw.multiline_textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    W, H = img.size
    margin = 10
    x = margin
    y = H - th - margin

    draw.rectangle(
        (x - 6, y - 4, x + tw + 6, y + th + 4),
        fill=(0, 0, 0),
    )
    draw.multiline_text((x, y), text, font=font, fill=(255, 255, 255))


def build_annotated_video(
    employment_id: int,
    employee_name: str,
    day: dt.date,
    screenshots: list,
    activity_by_id: dict[str, dict],
    target_width: int = 1280,   # 1280 ≈ 1K; use 1920 for ~2K
    max_frames: int | None = 60,
    fps: int = 2,
):
    """
    Download screenshot images, downscale, annotate, and build an MP4 using imageio.
    """
    if not screenshots:
        print("No screenshots to build video from.")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    screenshots_sorted = sorted(screenshots, key=lambda s: s.get("taken", 0))
    if max_frames is not None:
        screenshots_sorted = screenshots_sorted[:max_frames]

    frames: list[np.ndarray] = []

    for shot in screenshots_sorted:
        url = shot.get("url")
        shot_id = shot.get("id")
        taken_ts = shot.get("taken")
        activity_level = shot.get("activityLevel")
        activity_id = shot.get("activityId")

        if not url:
            print(f"Screenshot {shot_id} has no url, skipping.")
            continue

        activity = activity_by_id.get(activity_id, {})
        note = activity.get("note", "")

        app_name = "unknown"
        apps = shot.get("applications") or []
        if apps:
            primary_app = max(apps, key=lambda a: a.get("duration", 0))
            app_name = primary_app.get("applicationName") or "unknown"

        time_str = format_utc_timestamp(taken_ts) if taken_ts is not None else "unknown time"

        try:
            print(f"Downloading screenshot {shot_id} from {url}")
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")

            w, h = img.size
            if w > target_width:
                scale = target_width / float(w)
                new_size = (target_width, int(h * scale))
                img = img.resize(new_size, Image.LANCZOS)
                print(f"Resized {shot_id} from {w}x{h} to {new_size[0]}x{new_size[1]}")

            annotate_frame(img, employee_name, time_str, note, activity_level, app_name)

            frames.append(np.array(img))

        except Exception as e:
            print(f"Failed to download/process screenshot {shot_id}: {e}")

    if not frames:
        print("All screenshot downloads failed – no video created.")
        return None

    out_path = OUTPUT_DIR / f"{employment_id}_{day.isoformat()}.mp4"
    print(f"Saving video to {out_path} with {len(frames)} frames at {fps} fps")

    with imageio.get_writer(str(out_path), fps=fps, codec="libx264") as writer:
        for frame in frames:
            writer.append_data(frame)

    return out_path


# ---------- WHATSAPP HELPERS ----------

def whatsapp_upload_media(video_path: Path) -> str | None:
    """
    Uploads a video file to WhatsApp Cloud API and returns the media ID.
    """
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN):
        print("WhatsApp env vars not set, skipping upload.")
        return None

    if not video_path.is_file():
        print(f"Video file not found for upload: {video_path}")
        return None

    url = f"{WHATSAPP_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
    }

    print(f"Uploading video to WhatsApp: {video_path}")
    with video_path.open("rb") as f:
        files = {
            "file": (video_path.name, f, "video/mp4"),
        }
        data = {
            "type": "video/mp4",
            "messaging_product": "whatsapp",
        }
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)

    print(f"WhatsApp upload status: {resp.status_code}")
    if resp.status_code >= 400:
        print("Upload error body:")
        print(resp.text)
        return None

    try:
        res_json = resp.json()
    except Exception:
        print("Upload response is not JSON:")
        print(resp.text[:500])
        return None

    media_id = res_json.get("id")
    print(f"WhatsApp media id: {media_id}")
    return media_id


def whatsapp_send_video(media_id: str, caption: str):
    """
    Sends a WhatsApp message with an existing video media ID.
    """
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN and WHATSAPP_TO_NUMBER):
        print("WhatsApp env vars not fully set, skipping send.")
        return

    url = f"{WHATSAPP_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    body = {
        "messaging_product": "whatsapp",
        "to": WHATSAPP_TO_NUMBER,
        "type": "video",
        "video": {
            "id": media_id,
            "caption": caption,
        },
    }

    print(f"Sending WhatsApp message to {WHATSAPP_TO_NUMBER}")
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print(f"WhatsApp send status: {resp.status_code}")
    if resp.status_code >= 400:
        print("Send error body:")
        print(resp.text)


# ---------- MAIN ----------

def main():
    day, from_ts, to_ts = get_yesterday_range_utc()
    print(f"Building videos for date: {day}")
    print(f"From (unix): {from_ts}")
    print(f"To   (unix): {to_ts}")

    # DEBUG: check that all WhatsApp env vars are present
    print(
        "WhatsApp env present?:",
        bool(WHATSAPP_PHONE_NUMBER_ID),
        bool(WHATSAPP_TOKEN),
        bool(WHATSAPP_TO_NUMBER),
    )
    
    for employment_id, employee_name in EMPLOYMENTS.items():
        print(f"\n=== Processing employmentId {employment_id} ({employee_name}) ===")

        activities = fetch_activities_for_employment(employment_id, from_ts, to_ts)
        print(f"Total activities returned: {len(activities)}")

        print("\nActivities preview (first 2):")
        print(json.dumps(activities[:2], indent=2, default=str))

        activity_ids = [a["activityId"] for a in activities if "activityId" in a]
        if not activity_ids:
            print("No activities with activityId found – skipping this employment.")
            continue

        print("Activity IDs:")
        print(activity_ids)

        screenshots = fetch_screenshots_for_activities(activity_ids)
        print(f"Total screenshots returned: {len(screenshots)}")

        print("Screenshots preview (first 2):")
        print(json.dumps(screenshots[:2], indent=2, default=str))

        activity_by_id = {a["activityId"]: a for a in activities if "activityId" in a}

        video_path = build_annotated_video(
            employment_id,
            employee_name,
            day,
            screenshots,
            activity_by_id,
            target_width=1280,   # or 1920
            max_frames=120,
            fps=2,
        )

        if video_path:
            print(f"✅ Video created for {employee_name}: {video_path}")

            total_activities = len(activities)
            total_screens = len(screenshots)
            caption = (
                f"Daily activity for {employee_name} on {day.isoformat()} — "
                f"{total_activities} activities, {total_screens} screenshots."
            )

            media_id = whatsapp_upload_media(video_path)
            if media_id:
                whatsapp_send_video(media_id, caption)
            else:
                print("Skipping WhatsApp send because upload failed.")
        else:
            print(f"⚠️ No video created for {employee_name}.")


if __name__ == "__main__":
    main()
