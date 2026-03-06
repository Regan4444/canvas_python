#!/usr/bin/env python3
"""
Canvas SIS Import Status Checker

- Lists the most recent SIS imports for an account
- Shows workflow_state/status, counts, and errors (if available)
- Converts Canvas UTC timestamps to U.S. Central (America/Chicago)

Tested approach: uses /api/v1/accounts/{account_id}/sis_imports
"""

import sys
import csv
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------
# CONFIG (edit these)
# ---------------------------
CANVAS_BASE_URL = "paste domain here"
API_TOKEN = "paste your token here"  # You can hard-code it here
ACCOUNT_ID = "1"  # root account is often 1; set yours as needed

# How many recent imports to fetch (Canvas paginates; script handles pagination)
MAX_IMPORTS = 25

# Optional CSV export (set to a filename like "sis_imports_status.csv" to enable)
CSV_EXPORT_PATH = ""  # e.g. "sis_imports_status.csv"


# ---------------------------
# TIME HELPERS
# ---------------------------
CENTRAL_TZ = ZoneInfo("America/Chicago")  #  This code is designed for Central standard time in the US

def parse_canvas_iso8601(ts: Optional[str]) -> Optional[datetime]:
    """Parse Canvas ISO8601 timestamps (usually UTC, sometimes ends with 'Z')."""
    if not ts:
        return None
    ts = ts.strip()
    # Canvas commonly returns e.g. "2026-03-03T21:24:32Z"
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None

def utc_to_central_str(ts: Optional[str]) -> str:
    """Convert a Canvas UTC timestamp string to a Central-time display string."""
    dt = parse_canvas_iso8601(ts)
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_central = dt.astimezone(CENTRAL_TZ)
    # Example: 2026-03-03 15:24:32 CST/CDT
    return dt_central.strftime("%Y-%m-%d %H:%M:%S %Z")


# ---------------------------
# HTTP HELPERS
# ---------------------------
def canvas_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}

def request_json(url: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Any, str]:
    """Return (json_data, link_header)."""
    r = requests.get(url, headers=canvas_headers(), params=params, timeout=60)
    r.raise_for_status()
    return r.json(), r.headers.get("Link", "")

def parse_next_link(link_header: str) -> Optional[str]:
    """
    Parse Canvas-style Link header for rel="next".
    Example:
      <https://.../sis_imports?page=2&per_page=100>; rel="next",
      <https://.../sis_imports?page=1&per_page=100>; rel="current"
    """
    if not link_header:
        return None
    parts = [p.strip() for p in link_header.split(",")]
    for p in parts:
        if 'rel="next"' in p:
            start = p.find("<")
            end = p.find(">")
            if start != -1 and end != -1 and end > start:
                return p[start + 1 : end]
    return None

def list_sis_imports(account_id: str, limit: int = 25):
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/sis_imports"
    params = {"per_page": 100}
    all_items = []

    next_url = url
    next_params = params

    while next_url and len(all_items) < limit:
        data, link = request_json(next_url, params=next_params)

        # Canvas may return either:
        # 1) a list: [ {...}, {...} ]
        # 2) a wrapper dict: { "sis_imports": [ {...}, {...} ] }
        if isinstance(data, list):
            batch = data
        elif isinstance(data, dict) and isinstance(data.get("sis_imports"), list):
            batch = data["sis_imports"]
        else:
            batch = []

        all_items.extend(batch)

        next_url = parse_next_link(link)
        next_params = None

    return all_items[:limit]

def get_sis_import_detail(account_id: str, sis_import_id: int) -> Dict[str, Any]:
    url = f"{CANVAS_BASE_URL}/api/v1/accounts/{account_id}/sis_imports/{sis_import_id}"
    data, _ = request_json(url)
    return data if isinstance(data, dict) else {}


# ---------------------------
# MAIN LOGIC
# ---------------------------
def summarize_import(item: Dict[str, Any], detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Normalize fields we care about. Canvas returns a lot of variation depending on import type.
    """
    detail = detail or {}

    sis_id = item.get("id")
    workflow_state = item.get("workflow_state") or detail.get("workflow_state") or ""
    created_at = item.get("created_at") or detail.get("created_at")
    ended_at = item.get("ended_at") or detail.get("ended_at")
    updated_at = item.get("updated_at") or detail.get("updated_at")

    # Some useful fields often present:
    data_set_identifier = item.get("data_set_identifier") or detail.get("data_set_identifier") or ""
    progress = item.get("progress") or detail.get("progress")  # sometimes numeric
    processing_warnings = detail.get("processing_warnings") or item.get("processing_warnings") or []
    processing_errors = detail.get("processing_errors") or item.get("processing_errors") or []

    # statistics may appear in detail
    stats = detail.get("statistics") or item.get("statistics") or {}
    # Common stats keys: "accounts", "courses", "enrollments", "users", etc.
    # We'll just keep it as a compact string.
    stats_str = ""
    if isinstance(stats, dict) and stats:
        stats_str = ", ".join(f"{k}={v}" for k, v in stats.items())

    return {
        "id": sis_id,
        "workflow_state": workflow_state,
        "created_central": utc_to_central_str(created_at),
        "updated_central": utc_to_central_str(updated_at),
        "ended_central": utc_to_central_str(ended_at),
        "data_set_identifier": data_set_identifier,
        "progress": progress if progress is not None else "",
        "stats": stats_str,
        "errors_count": len(processing_errors) if isinstance(processing_errors, list) else "",
        "warnings_count": len(processing_warnings) if isinstance(processing_warnings, list) else "",
        "first_error": (processing_errors[0] if isinstance(processing_errors, list) and processing_errors else ""),
    }

def print_report(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("No SIS imports found.")
        return

    print(f"\nRecent SIS Imports (Account {ACCOUNT_ID}) — showing {len(rows)} most recent\n")
    for r in rows:
        print(f"ID: {r['id']}  | State: {r['workflow_state']}  | Progress: {r['progress']}")
        print(f"  Created (Central): {r['created_central']}")
        if r["ended_central"]:
            print(f"  Ended   (Central): {r['ended_central']}")
        elif r["updated_central"]:
            print(f"  Updated (Central): {r['updated_central']}")
        if r["data_set_identifier"]:
            print(f"  Data Set ID: {r['data_set_identifier']}")
        if r["stats"]:
            print(f"  Stats: {r['stats']}")
        if r["errors_count"]:
            print(f"  Errors: {r['errors_count']}  First error: {r['first_error']}")
        if r["warnings_count"]:
            print(f"  Warnings: {r['warnings_count']}")
        print("")

def export_csv(rows: List[Dict[str, Any]], path: str) -> None:
    fieldnames = [
        "id",
        "workflow_state",
        "progress",
        "created_central",
        "updated_central",
        "ended_central",
        "data_set_identifier",
        "stats",
        "errors_count",
        "warnings_count",
        "first_error",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"CSV exported to: {path}")

def main() -> int:
    if not API_TOKEN or "PASTE_YOUR_CANVAS_TOKEN_HERE" in API_TOKEN:
        print("ERROR: Set API_TOKEN at the top of the script.")
        return 2

    try:
        imports = list_sis_imports(ACCOUNT_ID, limit=MAX_IMPORTS)
    except requests.HTTPError as e:
        print(f"HTTP ERROR: {e}")
        return 2
    except requests.RequestException as e:
        print(f"REQUEST ERROR: {e}")
        return 2

    # Pull detail only for the most recent handful (avoids hammering API)
    rows: List[Dict[str, Any]] = []
    for item in imports:
        sis_id = item.get("id")
        detail = {}
        if sis_id is not None:
            try:
                detail = get_sis_import_detail(ACCOUNT_ID, int(sis_id))
            except Exception:
                detail = {}
        rows.append(summarize_import(item, detail))

    print_report(rows)

    if CSV_EXPORT_PATH:
        export_csv(rows, CSV_EXPORT_PATH)

    # Quick "stopped running" hint: show newest created timestamp
    newest = rows[0] if rows else None
    if newest and newest["created_central"]:
        print(f"Most recent import created (Central): {newest['created_central']} (ID {newest['id']})")

    return 0

if __name__ == "__main__":

    sys.exit(main())
