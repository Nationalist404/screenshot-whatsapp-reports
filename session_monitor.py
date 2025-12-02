import os
import json
import datetime as dt
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import imageio.v2 as imageio

# ---------- CONFIG ----------

API_BASE = "https://screenshotmonitor.com/api/v2"
SSM_TOKEN = os.environ["SSM_TOKEN"]  # ScreenshotMonitor API token

WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
WHATSAPP_TO_NUMBER = os.environ.get("WHATSAPP_TO_NUMBER")
WHATSAPP_BASE = "https://graph.facebook.com/v21.0"

# employmentId -> display name
EMPLOYMENTS = {
    433687: "VOID",
    433688: "Sufyan",  # you; add others like 123456: "Ali"
}

STATE_FILE = Path("session_state.json")
OUTPUT_DIR = Path("session_videos")

PKT = dt.timezone(dt.timedelta(hours=5))  # Pakistan time


# ---------- TIME HELPERS ----------

def utc_now_ts() -> int:
    """Current UTC timestamp (int seconds)."""
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def ts_to_pkt(ts: int) -> dt.datetime:
    dt_utc = dt.datetime.utcfromtimestamp(ts).replace(tzinfo=dt.timezone.utc)
    return dt_utc.astimezone(PKT)


def format_pkt_time(ts: int) -> str:
    return ts_to_pkt(ts).strftime("%I:%M %p")  # 12-hour, e.g. 11:05 AM


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    else:
        return f"{m}m"


# ---------- STATE ----------

def load_state():
    if STATE_FILE.is_file():
        try:
            with STATE_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sessions": {}}  # {employmentId_str: {activityId: {flags...}}}


def save_state(state):
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---------- SCREENSHOTMONITOR API ----------

def api_post(path: str, body):
    url = f"{API_BASE}{path}"
    headers = {
        "X-SSM-Token": SSM_TOKEN,
        "Content-Type": "application/json",
    }
    print(f"POST {url}")
    print("Body:", json.dumps(body, indent=2))
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print(f"Status: {resp.status_code}")
    if resp.status_code >= 400:
        print("Error body:", resp.text[:500])
        resp.raise_for_status()
    return resp.json()


def fetch_activities_for_today(employment_id: int):
    """
    Get today's activities (UTC day) for this employment.
    We only care about 'has this session started/ended yet'.
    """
    now_utc = dt.datetime.now(dt.timezone.utc)
    sod = dt.datetime(
        now_utc.year,
        now_utc.month,
        now_utc.day,
        0,
        0,
        tzinfo=dt.timezone.utc,
    )
    from_ts = int(sod.timestamp())
    to_ts = int(now_utc.timestamp()) + 600  # small cushion

    body = [{
        "employmentId": employment_id,
        "from": from_ts,
        "to": to_ts,
    }]
    data = api_post("/GetActivities", body)
    if not isinstance(data, list):
        print("Unexpected GetActivities response:", data)
        return []
    return data


def fetch_screenshots_for_activity(activity_id: str):
    body = [activity_id]
    data = api_post("/GetScreenshots", body)
    if not isinstance(data, list):
        print("Unexpected GetScreenshots response:", data)
        return []
    return [s for s in data if s.get("activityId") == activity_id]


# ---------- VIDEO BUILDING ----------

def get_font(size: int = 22):
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
    return ImageFont.load_default()


def annotate_frame(img, employee_name, note, screenshot):
    """
    Draw overlay similar to the daily video:

    VOID | 2025-12-01 06:44
    Activity: 88% | App: blender
    Note: qasim - southern energy
    """
    draw = ImageDraw.Draw(img)
    font = get_font(22)

    taken_ts = screenshot.get("taken")
    activity_level = screenshot.get("activityLevel")
    apps = screenshot.get("applications") or []

    # Line 1: Name + timestamp in PKT
    if taken_ts:
        dt_str = ts_to_pkt(taken_ts).strftime("%Y-%m-%d %H:%M")
        line1 = f"{employee_name} | {dt_str}"
    else:
        line1 = employee_name

    # Choose main application (prefer fromScreen=True, then longest duration)
    main_app = None
    if apps:
        main_app = max(
            apps,
            key=lambda a: (
                bool(a.get("fromScreen")),
                a.get("duration", 0),
            ),
        ).get("applicationName")

    # Line 2: Activity + App
    parts = []
    if activity_level is not None:
        parts.append(f"Activity: {activity_level}%")
    if main_app:
        parts.append(f"App: {main_app}")
    line2 = " | ".join(parts) if parts else ""

    # Line 3: Note
    line3 = f"Note: {note}" if note else ""

    # Build multi-line text
    lines = [line for line in (line1, line2, line3) if line]
    text = "\n".join(lines)

    if not text:
        return  # nothing to draw

    bbox = draw.multiline_textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    W, H = img.size
    margin = 10
    x = margin
    y = H - th - margin

    # Background box
    draw.rectangle(
        (x - 6, y - 4, x + tw + 6, y + th + 4),
        fill=(0, 0, 0),
    )
    # Text
    draw.multiline_text((x, y), text, font=font, fill=(255, 255, 255))


def build_session_video(
    employee_name,
    note,
    activity,
    screenshots,
    target_width=1280,
    fps=2,
):
    """Build a video for a single ScreenshotMonitor activity."""

    if not screenshots:
        print("No screenshots for this session.")
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    start_ts = activity["from"]
    # NOTE: 'to' is used only for naming / stats, not for message timestamp
    end_ts = activity.get("to") or start_ts

    # Average activity level for this session
    levels = [
        s.get("activityLevel")
        for s in screenshots
        if s.get("activityLevel") is not None
    ]
    avg_level = round(sum(levels) / len(levels)) if levels else None

    screenshots_sorted = sorted(
        screenshots,
        key=lambda s: s.get("taken", 0),
    )

    frames = []
    for s in screenshots_sorted:
        url = s.get("url")
        shot_id = s.get("id")
        if not url:
            continue

        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()

            img = Image.open(BytesIO(r.content)).convert("RGB")

            w, h = img.size
            if w > target_width:
                scale = target_width / float(w)
                img = img.resize(
                    (target_width, int(h * scale)),
                    Image.LANCZOS,
                )

            # annotate per screenshot with detailed overlay
            annotate_frame(img, employee_name, note, s)
            frames.append(np.array(img))

        except Exception as e:
            print(f"Failed to process screenshot {shot_id}: {e}")

    if not frames:
        print("No frames after processing.")
        return None

    day_str = ts_to_pkt(start_ts).date().isoformat()
    out_path = OUTPUT_DIR / f"{employee_name}_{day_str}_{activity['activityId']}.mp4"

    try:
        writer = imageio.get_writer(
            str(out_path),
            fps=fps,
            codec="libx264",
            format="FFMPEG",  # use ffmpeg plugin
        )
    except Exception as e:
        print(f"Could not create video writer for {out_path}: {e}")
        return None

    with writer:
        for frame in frames:
            writer.append_data(frame)

    return out_path, avg_level, len(frames)


# ---------- WHATSAPP HELPERS ----------

def whatsapp_send_text(message: str):
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN and WHATSAPP_TO_NUMBER):
        print("WhatsApp env missing, can't send text.")
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
        "text": {"preview_url": False, "body": message},
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print(f"WA text status: {resp.status_code}")
    if resp.status_code >= 400:
        print(resp.text[:500])


def whatsapp_upload_media(video_path: Path) -> str | None:
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN):
        print("WhatsApp env missing, can't upload media.")
        return None
    if not video_path.is_file():
        print(f"Video not found: {video_path}")
        return None
    url = f"{WHATSAPP_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    with video_path.open("rb") as f:
        files = {"file": (video_path.name, f, "video/mp4")}
        data = {"type": "video/mp4", "messaging_product": "whatsapp"}
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    print(f"WA upload status: {resp.status_code}")
    if resp.status_code >= 400:
        print(resp.text[:500])
        return None
    return resp.json().get("id")


def whatsapp_send_video(media_id: str, caption: str):
    if not (WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN and WHATSAPP_TO_NUMBER):
        print("WhatsApp env missing, can't send video.")
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
        "video": {"id": media_id, "caption": caption},
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    print(f"WA video status: {resp.status_code}")
    if resp.status_code >= 400:
        print(resp.text[:500])


# ---------- MAIN: SINGLE RUN ----------

def run_once():
    print(f"=== Session monitor run at {dt.datetime.now()} ===")
    state = load_state()

    # state["sessions"][employmentId_str][activityId] = {
    #   "notified_start": bool,
    #   "notified_end": bool
    # }

    for employment_id, name in EMPLOYMENTS.items():
        emp_key = str(employment_id)
        sessions_for_emp = state["sessions"].setdefault(emp_key, {})

        activities = fetch_activities_for_today(employment_id)
        print(f"{name}: {len(activities)} activities today")

        for a in activities:
            aid = a.get("activityId")
            if not aid:
                continue

            start_ts = a.get("from")
            end_ts = a.get("to")
            note = (a.get("note") or "").strip() or "(no note)"

            sess_state = sessions_for_emp.setdefault(
                aid, {"notified_start": False, "notified_end": False}
            )

            # START notification (seen for first time)
            if start_ts and not sess_state["notified_start"]:
                msg = (
                    f"▶ {name} STARTED session \"{note}\" "
                    f"at {format_pkt_time(start_ts)} (PKT)"
                )
                print("Sending START:", msg)
                whatsapp_send_text(msg)
                sess_state["notified_start"] = True

            # END notification
            if end_ts and not sess_state["notified_end"]:
                # 'end_ts' is the end of tracked/active work
                active_duration = max(0, end_ts - start_ts)

                # We treat "when we detect the end" as the human STOP time
                detected_end_ts = utc_now_ts()

                print(f"Session {aid} for {name} ended, building video...")
                screenshots = fetch_screenshots_for_activity(aid)
                video_info = build_session_video(name, note, a, screenshots)

                if video_info:
                    video_path, avg_level, frame_count = video_info
                    media_id = whatsapp_upload_media(video_path)
                    if media_id:
                        dur_str = format_duration(active_duration)
                        start_str = format_pkt_time(start_ts)
                        end_str = format_pkt_time(detected_end_ts)

                        caption = (
                            f"⏹ {name} STOPPED · \"{note}\"\n"
                            f"{start_str} – {end_str} PKT "
                            f"(active {dur_str}), {frame_count} screenshots."
                        )
                        if avg_level is not None:
                            caption += f" Avg activity {avg_level}%."
                        whatsapp_send_video(media_id, caption)
                    else:
                        # fallback text
                        dur_str = format_duration(active_duration)
                        msg = (
                            f"⏹ {name} FINISHED \"{note}\" "
                            f"(active {dur_str}) "
                            f"{format_pkt_time(start_ts)}–"
                            f"{format_pkt_time(detected_end_ts)} PKT"
                        )
                        whatsapp_send_text(msg)
                else:
                    dur_str = format_duration(active_duration)
                    msg = (
                        f"⏹ {name} finished \"{note}\" "
                        f"(active {dur_str}) "
                        f"{format_pkt_time(start_ts)}–"
                        f"{format_pkt_time(detected_end_ts)} PKT"
                    )
                    whatsapp_send_text(msg)

                sess_state["notified_end"] = True

    save_state(state)
    print("Run complete; state saved.")


if __name__ == "__main__":
    run_once()
