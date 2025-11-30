import os
import datetime as dt
import json
import requests


# ---- CONFIG ----

# Base URL for the API. Most of their endpoints look like /api/v2/Whatever,
# so base = https://screenshotmonitor.com should work.
API_BASE = "https://screenshotmonitor.com/api/v2"

SSM_TOKEN = os.environ["SSM_TOKEN"]


def api_get(path: str, params: dict | None = None):
    """
    Very small helper for GET requests to ScreenshotMonitor.
    You will tweak this to match exactly what your API docs show
    (query parameter names, maybe header auth, etc.).
    """
    if params is None:
        params = {}

    # --- 1) PASS AUTH VALUES ---
    # Check your API docs to see if these must be "companyKey" & "apiKey",
    # or "CompanyKey" & "ApiKey", or something else.
    params["companyKey"] = COMPANY_KEY
    params["apiKey"] = API_KEY

    url = f"{API_BASE}{path}"
    print(f"Calling: {url}")
    print(f"With params: {params}")

    resp = requests.get(url, params=params, timeout=60)
    print(f"Status code: {resp.status_code}")
    resp.raise_for_status()
    try:
        return resp.json()
    except Exception:
        print("Response is not JSON. Raw text:")
        print(resp.text[:1000])
        raise


def main():
    # ---- WHAT DAY TO TEST ----
    # Let’s just ask for "yesterday", in case the endpoint needs a date range.
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    print(f"Testing ScreenshotMonitor API for date: {yesterday}")

    # ---- CHOOSE A SIMPLE ENDPOINT FROM YOUR API DOCS ----
    #
    # In your browser, open the API docs page you linked me:
    # https://screenshotmonitor.com/apidoc/
    #
    # Find any simple GET endpoint that:
    #   - Returns a list of projects, employees, activities, or time entries
    #   - Uses only query parameters (no complex body)
    #
    # Examples of what to look for in the left menu (names may differ):
    #   - "Projects - Get projects"
    #   - "Employees - Get employees"
    #   - "Activities - Get activities"
    #
    # Once you pick one:
    #   1) Copy the path (e.g. "/api/v2/GetProjects")
    #   2) Copy the query parameter names it needs ("from", "to", "employeeId", etc.)
    #
    # Then plug them into the call below.

    # === EDIT HERE: set the endpoint path from your docs ===
    TEST_ENDPOINT = "/GetCommonData"  # <-- replace with a real one from docs

    # === EDIT HERE: match the parameter names from docs ===
    params = {
        # Example if docs show `from` & `to`:
        # "from": yesterday.isoformat(),
        # "to": today.isoformat(),

        # If the endpoint doesn’t require dates, just leave params = {} or remove them.
    }

    data = api_get(TEST_ENDPOINT, params)

    # Print a small preview to the logs
    print("\n=== RAW JSON (first 1-2 items) ===")
    if isinstance(data, list):
        preview = data[:2]
    elif isinstance(data, dict) and "data" in data:
        preview = data["data"][:2] if isinstance(data["data"], list) else data
    else:
        preview = data

    print(json.dumps(preview, indent=2, default=str))


if __name__ == "__main__":
    main()
