import requests
import csv
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CANVAS_BASE_URL = "paste your domain here"
API_TOKEN = "paste your token here"
ACCOUNT_ID = "1"

OUTPUT_FILE = r"C:\Users\Owner\Documents\Python Scripts\sis_import_status.csv"  #  enter the path to the csv file you wish to log to.

# nightly jobs → allow up to 36 hours
MAX_AGE_HOURS = 36

CENTRAL = ZoneInfo("America/Chicago")

def parse_ts(ts):
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

headers = {"Authorization": f"Bearer {API_TOKEN}"}

# get last imports
url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/sis_imports"
r = requests.get(url, headers=headers, params={"per_page": 25}, timeout=60)
r.raise_for_status()

imports = r.json()["sis_imports"]

rows = []

for imp in imports:

    detail_url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/sis_imports/{imp['id']}"
    d = requests.get(detail_url, headers=headers, timeout=60).json()

    created = parse_ts(d["created_at"])
    created_central = created.astimezone(CENTRAL)

    age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600

    user = d.get("user") or {}

    warnings = d.get("processing_warnings") or []
    errors = d.get("processing_errors") or []

    status = "OK"
    if age_hours > MAX_AGE_HOURS:
        status = "STALE"

    rows.append({
        "import_id": d["id"],
        "created_central": created_central.strftime("%Y-%m-%d %H:%M:%S"),
        "workflow_state": d["workflow_state"],
        "initiated_by": user.get("login_id"),
        "initiator_name": user.get("name"),
        "warnings": len(warnings),
        "errors": len(errors),
        "age_hours": round(age_hours,2),
        "status": status
    })

# write CSV
with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "import_id",
            "created_central",
            "workflow_state",
            "initiated_by",
            "initiator_name",
            "warnings",
            "errors",
            "age_hours",
            "status"
        ]
    )

    writer.writeheader()

    for r in rows:
        writer.writerow(r)


print("Report written to:", OUTPUT_FILE)
