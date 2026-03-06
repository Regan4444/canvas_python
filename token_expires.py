import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CANVAS_BASE_URL = "https://grayson.instructure.com"
API_TOKEN = "4480~PturLY3URL2MCx9vzthmHUU488c4XDEcKRkU27mzUXPGT4M9uP2HmGZ6K79xTzC7"     # your monitoring token (yours, not Robbie’s)
ACCOUNT_ID = "1"
MAX_AGE_HOURS = 6             # set to whatever makes sense

CENTRAL = ZoneInfo("America/Chicago")

def parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)

headers = {"Authorization": f"Bearer {API_TOKEN}"}
url = f"{CANVAS_BASE_URL}/api/v1/accounts/{ACCOUNT_ID}/sis_imports"
r = requests.get(url, headers=headers, params={"per_page": 1}, timeout=60)
r.raise_for_status()
latest = r.json()["sis_imports"][0]

created = parse_ts(latest["created_at"])
age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
created_central = created.astimezone(CENTRAL).strftime("%Y-%m-%d %H:%M:%S %Z")

print(f"Latest SIS import: ID {latest['id']} at {created_central} ({age_hours:.2f} hours ago)")

if age_hours > MAX_AGE_HOURS:
    raise SystemExit(f"ALERT: SIS imports are stale (> {MAX_AGE_HOURS} hours).")