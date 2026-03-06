#!/usr/bin/env python3
"""
Canvas: Student activity in a specific course for a fixed semester window (Jan 19 -> Mar 22).

Outputs a single CSV timeline including:
- Page views (URLs + timestamps) via Page Views Query API (async + polling)
- Submissions events (submitted/graded/posted) via course students/submissions endpoint

Docs:
- Users: Page Views Query endpoints (Users API) https://developerdocs.instructure.com/services/canvas/resources/users
- Submissions API https://developerdocs.instructure.com/services/canvas/resources/submissions
"""

import argparse
import csv
import datetime as dt
import gzip
import json
import time
from typing import Any, Dict, List, Optional
import requests

# ====== EDIT THESE DEFAULTS ======
CANVAS_BASE_URL = "https://grayson.instructure.com"
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
# =================================


def headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def parse_link_header(link_header: str) -> Dict[str, str]:
    links = {}
    if not link_header:
        return links
    for part in link_header.split(","):
        section = [s.strip() for s in part.split(";")]
        if len(section) < 2:
            continue
        url = section[0]
        rel = None
        for s in section[1:]:
            if s.startswith('rel='):
                rel = s.split("=", 1)[1].strip().strip('"')
        if rel and url.startswith("<") and url.endswith(">"):
            links[rel] = url[1:-1]
    return links


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    r = requests.get(url, headers=headers(), params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def post_json(url: str, payload: Dict[str, Any]) -> Any:
    r = requests.post(
        url,
        headers={**headers(), "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def paged_get_list(url: str, params: Dict[str, Any]) -> List[Any]:
    out: List[Any] = []
    next_url = url
    next_params = params
    while next_url:
        r = requests.get(next_url, headers=headers(), params=next_params, timeout=60)
        r.raise_for_status()
        out.extend(r.json())
        links = parse_link_header(r.headers.get("Link", ""))
        if "next" in links:
            next_url = links["next"]
            next_params = None
        else:
            next_url = None
    return out


def chicago_range_to_utc_iso(year: int) -> tuple[str, str]:
    """
    Convert local America/Chicago dates to an inclusive/exclusive UTC ISO range.
    - Start: Jan 19 00:00:00 America/Chicago
    - End:   Mar 22 23:59:59 America/Chicago (we convert to UTC and keep inclusive)
    Uses Python 3.9+ zoneinfo.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Chicago")
    start_local = dt.datetime(year, 1, 19, 0, 0, 0, tzinfo=tz)
    end_local = dt.datetime(year, 3, 22, 23, 59, 59, tzinfo=tz)

    start_utc = start_local.astimezone(dt.timezone.utc)
    end_utc = end_local.astimezone(dt.timezone.utc)

    def iso_z(x: dt.datetime) -> str:
        return x.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return iso_z(start_utc), iso_z(end_utc)


def poll_page_views_query(base_url: str, user_id: int, query_id: str,
                          poll_seconds: int = 2, timeout_seconds: int = 180) -> str:
    status_url = f"{base_url}/api/v1/users/{user_id}/page_views/query/{query_id}"
    start = time.time()
    while True:
        data = get_json(status_url)
        status = (data.get("status") or "").lower()
        results_url = data.get("results_url") or data.get("result_url") or data.get("url")
        if status in ("complete", "completed", "finished") and results_url:
            return results_url
        if status in ("failed", "error"):
            raise RuntimeError(f"Page views query failed: {data}")
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for page views query (last status={status}, data={data})")
        time.sleep(poll_seconds)


def fetch_page_views_for_course(base_url: str, user_id: int, course_id: int,
                                start_time: str, end_time: str) -> List[Dict[str, Any]]:
    """
    Uses the stable endpoint:
      GET /api/v1/users/:user_id/page_views?start_time=...&end_time=...
    and filters to the given course.
    """
    url = f"{base_url}/api/v1/users/{user_id}/page_views"
    params = {
        "start_time": start_time,
        "end_time": end_time,
        "per_page": 100,
    }

    out: List[Dict[str, Any]] = []
    next_url = url
    next_params = params

    while next_url:
        r = requests.get(next_url, headers=headers(), params=next_params, timeout=60)
        r.raise_for_status()
        data = r.json()

        for pv in data:
            # Different Canvas builds vary slightly; filter defensively
            ctx_type = (pv.get("context_type") or "").lower()
            ctx_id = pv.get("context_id")
            if (ctx_type == "course" and str(ctx_id) == str(course_id)) or (str(pv.get("course_id")) == str(course_id)):
                out.append(pv)

        links = parse_link_header(r.headers.get("Link", ""))
        if "next" in links:
            next_url = links["next"]
            next_params = None
        else:
            next_url = None

    return out



def fetch_submissions_activity(base_url: str, course_id: int, user_id: int) -> List[Dict[str, Any]]:
    url = f"{base_url}/api/v1/courses/{course_id}/students/submissions"
    params = {
        "student_ids[]": user_id,
        "per_page": 100,
        "include[]": ["assignment", "submission_history"],
    }
    return paged_get_list(url, params)


def in_range(ts: Optional[str], start_iso: str, end_iso: str) -> bool:
    if not ts:
        return False
    return start_iso <= ts <= end_iso


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=CANVAS_BASE_URL)
    ap.add_argument("--course", type=int, required=True, help="Canvas course_id")
    ap.add_argument("--student", type=int, required=True, help="Canvas user_id (student)")
    ap.add_argument("--year", type=int, default=2026, help="Year for Jan19–Mar22 window")
    ap.add_argument("--out", default="student_course_activity.csv", help="Output CSV")
    args = ap.parse_args()

    base_url = args.base_url.rstrip("/")
    start_time, end_time = chicago_range_to_utc_iso(args.year)

    timeline: List[Dict[str, Any]] = []

    # Page views
    try:
        pvs = fetch_page_views_for_course(base_url, args.student, args.course, start_time, end_time)
        for pv in pvs:
            timeline.append({
                "timestamp": pv.get("created_at") or pv.get("timestamp") or "",
                "type": "page_view",
                "detail": pv.get("url") or pv.get("asset") or pv.get("interaction") or "",
                "extra": (pv.get("controller") or "") + ("/" + pv.get("action") if pv.get("action") else ""),
            })
    except Exception as e:
        timeline.append({
            "timestamp": "",
            "type": "error",
            "detail": "page_views_query_failed",
            "extra": str(e),
        })

    # Submissions
    subs = fetch_submissions_activity(base_url, args.course, args.student)
    for s in subs:
        a = s.get("assignment") or {}
        title = a.get("name") or f"assignment_id={a.get('id')}"

        submitted_at = s.get("submitted_at")
        graded_at = s.get("graded_at")
        posted_at = s.get("posted_at")

        if in_range(submitted_at, start_time, end_time):
            timeline.append({
                "timestamp": submitted_at,
                "type": "submission",
                "detail": title,
                "extra": f"score={s.get('score')} state={s.get('workflow_state')} late={s.get('late')} missing={s.get('missing')}",
            })
        if in_range(graded_at, start_time, end_time):
            timeline.append({
                "timestamp": graded_at,
                "type": "graded",
                "detail": title,
                "extra": f"score={s.get('score')} grader_id={s.get('grader_id')}",
            })
        if in_range(posted_at, start_time, end_time):
            timeline.append({
                "timestamp": posted_at,
                "type": "posted",
                "detail": title,
                "extra": f"score={s.get('score')}",
            })

        # Flag your exact scenario
        if (s.get("submitted_at") is None) and (s.get("score") is not None):
            # only include this flag if the grade event timestamp (if any) is inside the window
            if in_range(graded_at or posted_at or "", start_time, end_time) or (graded_at is None and posted_at is None):
                timeline.append({
                    "timestamp": graded_at or posted_at or "",
                    "type": "flag",
                    "detail": title,
                    "extra": f"NO_SUBMISSION_BUT_HAS_SCORE score={s.get('score')} missing={s.get('missing')}",
                })

    timeline.sort(key=lambda r: r["timestamp"] or "9999-99-99T99:99:99Z")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "type", "detail", "extra"])
        w.writeheader()
        w.writerows(timeline)

    print(f"Wrote {len(timeline)} row(s) to {args.out}")
    print(f"Date window (UTC): {start_time} to {end_time}")

if __name__ == "__main__":
    main()
