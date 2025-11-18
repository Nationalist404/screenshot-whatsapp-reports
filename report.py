import os
import json
import datetime as dt
import tempfile
import subprocess

import requests

# ----- CONFIG -----
TIMEZONE_OFFSET_HOURS = 5  # Asia/Karachi (UTC+5)

SSM_API_KEY = os.environ["SCREENSHOTMONITOR_API_KEY"]
WA_TOKEN = os.environ["WHATSAPP_TOKEN"]
WA_PHONE_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
WA_TARGET = os.environ["WHATSAPP_TARGET_PHONE"]  # e.g. 923001234567


# ----- DATE HELPERS -----
def today_date():
    """Return today's date in your timezone (Asia/Karachi)."""
    now_utc = dt.datetime.utcnow()
    now_local = now_utc + dt.timedelta(hours=TIMEZONE_OFFSET_HOURS)
    return now_local.date()


# ----- SCREENSHOTMONITOR -----
def fetch_today_entries():
    """
    TODO: wire this to ScreenshotMonitor's API.

    This function MUST return a list of dicts like:

    [
      {
        "employee": "Ali",
        "seconds": 600,                      # duration in seconds
        "note": "Argonics shading",
        "timestamp": "2025-11-16T10:15:00Z", # ISO string
        "screenshot_url": "https://..."
      },
      ...
    ]

    You (or your dev) can get the exact endpoint + JSON shape
    from ScreenshotMonitor's "API" section under My Account.

    Steps:
      1. Call their API with your key and date = today_date().
      2. Look at the JSON it returns.
      3. Map fields into the format above.
    """
    raise NotImplementedError(
        "fetch_today_entries() still needs to be connected to ScreenshotMonitor API.\n"
        "Once you have a sample JSON from their API, paste it into ChatGPT and "
        "ask to help you fill this function."
    )


def group_by_employee(entries):
    grouped = {}
    for e in entries:
        grouped.setdefault(e["employee"], []).append(e)
    return grouped


# ----- VIDEO CREATION (using ffmpeg) -----
def build_timelapse_mp4(employee, records, tmpdir):
    """Download screenshots & build a timelapse MP4. Returns file path or None."""
    if not records:
        return None

    emp_dir = os.path.join(tmpdir, employee.replace(" ", "_"))
    os.makedirs(emp_dir, exist_ok=True)

    # sort by timestamp
    recs = sorted(records, key=lambda r: r["timestamp"])
    image_paths = []

    for i, r in enumerate(recs, start=1):
        url = r.get("screenshot_url")
        if not url:
            continue
        img_path = os.path.join(emp_dir, f"{i:03d}.jpg")
        resp = requests.get(url)
        if resp.status_code == 200:
            with open(img_path, "wb") as f:
                f.write(resp.content)
            image_paths.append(img_path)

    if not image_paths:
        return None

    # ffmpeg expects 001.jpg, 002.jpg, ...
    out_path = os.path.join(tmpdir, f"{employee.replace(' ', '_')}.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "2",  # 2 frames per second
        "-i",
        os.path.join(emp_dir, "%03d.jpg"),
        "-vf",
        "scale=1280:-1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def summarize_hours_and_notes(records):
    total_seconds = sum(r.get("seconds", 0) for r in records)
    hours = round(total_seconds / 3600, 2)

    notes = sorted(
        {
            (r.get("note") or "").strip()
            for r in records
            if (r.get("note") or "").strip()
        }
    )
    if not notes:
        notes = ["No specific notes entered."]
    return hours, notes


# ----- WHATSAPP HELPERS -----
def upload_media_to_whatsapp(filepath):
    """Upload MP4 and get media_id."""
    url = f"https://graph.facebook.com/v20.0/{WA_PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {WA_TOKEN}"}
    files = {"file": open(filepath, "rb")}
    data = {"messaging_product": "whatsapp"}

    resp = requests.post(url, headers=headers, files=files, data=data)
    resp.raise_for_status()
    j = resp.json()
    return j["id"]


def send_whatsapp_video(media_id, caption):
    url = f"https://graph.facebook.com/v20.0/{WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": WA_TARGET,
        "type": "video",
        "video": {
            "id": media_id,
            "caption": caption,
        },
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    resp.raise_for_status()


# ----- MAIN -----
def main():
    date_str = today_date().isoformat()
    try:
        entries = fetch_today_entries()
    except NotImplementedError as e:
        # For now, fail clearly so you know this part isn't wired yet
        print(str(e))
        return

    if not entries:
        print("No entries today.")
        return

    grouped = group_by_employee(entries)

    with tempfile.TemporaryDirectory() as tmpdir:
        for employee, records in grouped.items():
            print(f"Processing {employee} with {len(records)} records...")
            mp4_path = build_timelapse_mp4(employee, records, tmpdir)
            hours, notes = summarize_hours_and_notes(records)

            if not mp4_path:
                print(f"No screenshots for {employee}, skipping video.")
                continue

            media_id = upload_media_to_whatsapp(mp4_path)
            notes_text = "\n".join(f"• {n}" for n in notes)
            caption = (
                f"Daily Summary – {date_str}\n"
                f"Employee: {employee}\n"
                f"Total Hours: {hours}\n\n"
                f"Notes:\n{notes_text}"
            )
            send_whatsapp_video(media_id, caption)
            print(f"Sent summary for {employee}.")


if __name__ == "__main__":
    main()
