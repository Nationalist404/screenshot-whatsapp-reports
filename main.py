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

OUTPUT_DIR = Path("out")

# If you ever want to limit to certain employments, put their IDs here:
# e.g. EMPLOYMENT_FILTER = {433687, 123456}
EMPLOYMENT_FILTER: set[int] | None = None

# ---- CONFIG: WhatsApp Cloud API (from GitHub secrets) ----

WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
WHATSAPP_TO_NUMBER = os.environ.get("WHATSAPP_TO_NUMBER")
WHATSAPP_BASE = "https://graph.facebook.com/v21.0"  # adjust version if needed



# ---- MANUAL EMPLOYMENTS FALLBACK ----
# Use employmentId -> display name.
# You already know 433687 ("VOID" / you).
EMPLOYMENTS_MANUAL: dict[int, str] = {
    433687: "VOID",          # Qasim - Southern Energy
    433688: "Sufyan",
    # 123457: "Ahmed",
    # Add more as you hire them
}

# ---------- HTTP HELPERS FOR SCREENSHOTMONITOR ----------

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


def api_get(path: str, params=None):
    """Simple GET helper for /GetCommonData."""
    url = f"{API_BASE}{path}"
    headers = {"X-SSM-Token": SSM_TOKEN}
    resp = requests.get(url, headers=headers, params=params or {}, timeout=60)
    print(f"GET {url} -> {resp.status_code}")
    if resp.status_code >= 400:
        print("=== ERROR RESPONSE BODY (first 1000 chars) ===")
        print(resp.text[:1000])
        resp.raise_for_status()
    return resp.json()


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

# ---- TIMEZONE & DURATION HELPERS (PKT) ----
PKT = dt.timezone(dt.timedelta(hours=5))  # UTC+5

def to_unix_seconds(dt_obj: dt.datetime) -> int:
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt.timezone.utc)
    return int((dt_obj - epoch).total_seconds())

def get_yesterday_range_pkt():
    """
    Previous *calendar day in PKT* (00:00–24:00 PKT), converted to UTC
    unix timestamps for ScreenshotMonitor API.
    """
    today_pkt = dt.datetime.now(PKT).date()
    yesterday_pkt = today_pkt - dt.timedelta(days=1)

    start_pkt = dt.datetime.combine(yesterday_pkt, dt.time(0, 0), tzinfo=PKT)
    end_pkt   = dt.datetime.combine(today_pkt,    dt.time(0, 0), tzinfo=PKT)

    start_utc = start_pkt.astimezone(dt.timezone.utc)
    end_utc   = end_pkt.astimezone(dt.timezone.utc)

    return yesterday_pkt, to_unix_seconds(start_utc), to_unix_seconds(end_utc)

def ts_to_pkt(ts: int) -> dt.datetime:
    dt_utc = dt.datetime.utcfromtimestamp(ts).replace(tzinfo=dt.timezone.utc)
    return dt_utc.astimezone(PKT)

def format_pkt_time(ts: int) -> str:
    # 12-hour (still used in summaries)
    return ts_to_pkt(ts).strftime("%I:%M %p")

def format_pkt_timestamp_24(ts: int) -> str:
    # 24-hour for video overlay
    return ts_to_pkt(ts).strftime("%Y-%m-%d %H:%M (PKT)")
    


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    else:
        return f"{minutes}m"

# ---------- EMPLOYMENTS (ALL EMPLOYEES) ----------

def fetch_all_employments() -> dict[int, str]:
    """
    Try to call /GetCommonData and build {employmentId: human_name}.
    If that fails (500 etc), fall back to EMPLOYMENTS_MANUAL.
    """
    try:
        data = api_get("/GetCommonData")
        employments_raw = data.get("employments") or data.get("Employments") or []
        employees_raw = data.get("employees") or data.get("Employees") or []

        employees_by_id = {}
        for emp in employees_raw:
            emp_id = emp.get("id") or emp.get("employeeId")
            if not emp_id:
                continue
            first = emp.get("firstName") or ""
            last = emp.get("lastName") or ""
            name = (first + " " + last).strip() or emp.get("name") or f"Employee {emp_id}"
            employees_by_id[emp_id] = name

        employment_map: dict[int, str] = {}
        for e in employments_raw:
            eid = e.get("id") or e.get("employmentId")
            if not eid:
                continue

            name = (
                e.get("name")
                or e.get("employmentName")
                or e.get("employeeName")
                or ""
            )

            emp_id = e.get("employeeId")
            if not name and emp_id in employees_by_id:
                name = employees_by_id[emp_id]

            if not name:
                name = f"Employment {eid}"

            employment_map[int(eid)] = name

        if employment_map:
            print(f"Discovered {len(employment_map)} employments from GetCommonData:")
            for eid, name in employment_map.items():
                print(f"  {eid}: {name}")
            return employment_map

        print("GetCommonData returned no employments, will try manual fallback...")

    except Exception as e:
        print(f"Failed to fetch common data: {e}")

    # ---- Fallback to manual list ----
    if EMPLOYMENTS_MANUAL:
        print("Falling back to EMPLOYMENTS_MANUAL mapping:")
        for eid, name in EMPLOYMENTS_MANUAL.items():
            print(f"  {eid}: {name}")
        return EMPLOYMENTS_MANUAL.copy()

    print("No employments available (API failed and EMPLOYMENTS_MANUAL is empty).")
    return {}



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

def get_overlay_font(size: int = 22) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Try to load a bigger TrueType font; fall back to default if not available.
    """
    candidates = [
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # Fallback
    return ImageFont.load_default()


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
    font = get_overlay_font(size=22)

    # Normalize values
    if activity_level is None:
        activity_level = 0
    if app_name is None or app_name == "":
        app_name = "unknown"
    if note is None:
        note = ""

    # Shorten long notes
    max_note_len = 80
    if len(note) > max_note_len:
        note = note[: max_note_len - 3] + "..."

    line1 = f"{employee_name} | {time_str}"
    line2 = f"Activity: {activity_level}% | App: {app_name}"
    line3 = f"Note: {note}" if note else ""

    text = f"{line1}\n{line2}" if not line3 else f"{line1}\n{line2}\n{line3}"

    # Compute text bounding box
    bbox = draw.multiline_textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    W, H = img.size
    margin = 10
    x = margin
    y = H - th - margin

    # Background
    draw.rectangle(
        (x - 6, y - 4, x + tw + 6, y + th + 4),
        fill=(0, 0, 0),
    )
    # Text
    draw.multiline_text((x, y), text, font=font, fill=(255, 255, 255))



def build_annotated_video(
    employment_id: int,
    employee_name: str,
    day: dt.date,
    screenshots: list,
    activity_by_id: dict[str, dict],
    target_width: int = 1280,
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

        # Session note from the activity
        activity = activity_by_id.get(activity_id, {})
        note = activity.get("note", "") or ""

        # Main application name
        app_name = "unknown"
        apps = shot.get("applications") or []
        if apps:
            primary_app = max(apps, key=lambda a: a.get("duration", 0))
            app_name = primary_app.get("applicationName") or "unknown"

        # PKT 24h time for overlay
        if taken_ts is not None:
            time_str = format_pkt_timestamp_24(taken_ts)
        else:
            time_str = "unknown time"

        try:
            print(f"Downloading screenshot {shot_id} from {url}")
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")

            # Downscale if needed
            w, h = img.size
            if w > target_width:
                scale = target_width / float(w)
                new_size = (target_width, int(h * scale))
                img = img.resize(new_size, Image.LANCZOS)
                print(
                    f"Resized {shot_id} from {w}x{h} to "
                    f"{new_size[0]}x{new_size[1]}"
                )

            # Draw overlay
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


def whatsapp_send_text(message: str):
    """
    Send a plain text WhatsApp message (used when there is no video
    or when an employee has no activity on a given day).
    """
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN and WHATSAPP_TO_NUMBER):
        print("WhatsApp env vars not fully set, skipping text send.")
        return

    url = f"{WHATSAPP_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    body = {
        "messaging_product": "whatsapp",
        "to": WHATSAPP_TO_NUMBER,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message,
        },
    }

    print(f"Sending WhatsApp TEXT to {WHATSAPP_TO_NUMBER}")
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print(f"WhatsApp text send status: {resp.status_code}")
    if resp.status_code >= 400:
        print("Text send error body:")
        print(resp.text)


def build_activity_summary(
    employee_name: str,
    day: dt.date,
    activities: list[dict],
    screenshots: list[dict],
) -> str:
    """
    Build a human-readable daily summary for WhatsApp:
    - PKT 12h times
    - grouped by note
    - session start/end, duration, avg activity
    """

    if not activities:
        # No work at all for this person today
        return f"No tracked activity for {employee_name} on {day.isoformat()}."

    # Index screenshot activity levels by activityId -> avg
    level_index: dict[str, dict] = {}
    for s in screenshots:
        aid = s.get("activityId")
        lvl = s.get("activityLevel")
        if aid is None or lvl is None:
            continue
        bucket = level_index.setdefault(aid, {"sum": 0, "count": 0})
        bucket["sum"] += lvl
        bucket["count"] += 1

    # Group sessions by note
    sessions_by_note: dict[str, list[dict]] = {}
    earliest = None
    latest = None
    total_duration = 0

    for a in activities:
        aid = a.get("activityId")
        start = a.get("from")
        end = a.get("to")
        note = (a.get("note") or "").strip() or "(no note)"

        if start is None or end is None:
            continue

        dur = max(0, end - start)
        total_duration += dur

        if earliest is None or start < earliest:
            earliest = start
        if latest is None or end > latest:
            latest = end

        # Average activity level for this session (from screenshots)
        avg_level = None
        stats = level_index.get(aid)
        if stats and stats["count"] > 0:
            avg_level = round(stats["sum"] / stats["count"])

        session = {
            "start": start,
            "end": end,
            "duration": dur,
            "avg_level": avg_level,
        }
        sessions_by_note.setdefault(note, []).append(session)

    lines: list[str] = []

    # Header line
    lines.append(f"{employee_name} — {day.isoformat()} (PKT)")

    # Overall daily range + total time
    if earliest is not None and latest is not None:
        lines.append(
            f"Overall: {len(activities)} session(s), "
            f"{format_pkt_time(earliest)}–{format_pkt_time(latest)}, "
            f"total {format_duration(total_duration)}."
        )

    # To keep caption reasonably short, cap detailed lines:
    MAX_SESSION_LINES = 40
    printed_sessions = 0
    total_sessions = len(activities)

    # Per-note breakdown
    for note, sessions in sessions_by_note.items():
        sessions_sorted = sorted(sessions, key=lambda s: s["start"])
        note_duration = sum(s["duration"] for s in sessions_sorted)

        lines.append(
            f"\n{note}: {len(sessions_sorted)} session(s), "
            f"{format_duration(note_duration)} total."
        )

        for idx, s in enumerate(sessions_sorted, start=1):
            if printed_sessions >= MAX_SESSION_LINES:
                break

            start_str = format_pkt_time(s["start"])
            end_str = format_pkt_time(s["end"])
            dur_str = format_duration(s["duration"])
            if s["avg_level"] is not None:
                level_part = f", avg activity {s['avg_level']}%"
            else:
                level_part = ""

            lines.append(
                f"{idx}) {start_str}–{end_str} ({dur_str}{level_part})"
            )
            printed_sessions += 1

    if printed_sessions < total_sessions:
        remaining = total_sessions - printed_sessions
        lines.append(f"... plus {remaining} more session(s).")

    return "\n".join(lines)

# ---------- MAIN ----------

def main():
    day, from_ts, to_ts = get_yesterday_range_pkt()
    print(f"Building videos for date: {day}")
    print(f"From (unix): {from_ts}")
    print(f"To   (unix): {to_ts}")

    print(
        "WhatsApp env present?:",
        bool(WHATSAPP_PHONE_NUMBER_ID),
        bool(WHATSAPP_TOKEN),
        bool(WHATSAPP_TO_NUMBER),
    )

    employment_map = fetch_all_employments()
    if not employment_map:
        print("No employments found – aborting.")
        return

    for employment_id, employee_name in employment_map.items():
        print(f"\n=== Processing employmentId {employment_id} ({employee_name}) ===")

        activities = fetch_activities_for_employment(employment_id, from_ts, to_ts)
        print(f"Total activities returned: {len(activities)}")

        # If NO activity at all: send "did not work" message and skip
        if not activities:
            print("No activities for this employment.")
            summary = build_activity_summary(employee_name, day, activities, [])
            whatsapp_send_text(summary)
            continue

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
            target_width=1280,
            max_frames=3000,  # or 120 if you want ~1 min at 2 fps
            fps=3,
        )

        # Build the detailed PKT summary for this person & day
        summary = build_activity_summary(employee_name, day, activities, screenshots)

        if video_path:
            print(f"✅ Video created for {employee_name}: {video_path}")

            media_id = whatsapp_upload_media(video_path)
            if media_id:
                whatsapp_send_video(media_id, summary)
            else:
                print("Skipping WhatsApp video send because upload failed.")
                whatsapp_send_text(summary)
        else:
            print(f"⚠️ No video created for {employee_name}. Sending text summary only.")
            whatsapp_send_text(summary)



if __name__ == "__main__":
    main()
