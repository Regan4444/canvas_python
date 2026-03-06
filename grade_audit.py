#!/usr/bin/env python3
"""
Canvas Grade Change Audit lookup (who entered/changed a grade, and when).

Requires: pip install requests
Usage examples:
  python grade_audit.py --course 12345 --assignment 67890 --students 111,222
  python grade_audit.py --course 12345 --assignment 67890 --students-file students.txt --days 365

Notes:
- Uses Canvas Grade Change Log (Audit) API:
  GET /api/v1/audit/grade_change?course_id=...&assignment_id=...&student_id=...
- You must have admin rights to query broadly; as a domain admin you should. :contentReference[oaicite:2]{index=2}
"""

import argparse
import csv
import datetime as dt
import sys
import requests
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs

# ====== EDIT THESE DEFAULTS ======
CANVAS_BASE_URL = "https://grayson.instructure.com"  # <- change if needed
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"                      # <- paste token
# =================================


def iso_z(d: dt.datetime) -> str:
    # Canvas accepts ISO8601; use UTC "Z"
    return d.replace(microsecond=0, tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_link_header(link_header: str) -> Dict[str, str]:
    """
    Parse RFC5988 Link header: <url>; rel="next", <url>; rel="current", ...
    """
    links = {}
    if not link_header:
        return links
    parts = link_header.split(",")
    for p in parts:
        section = p.strip().split(";")
        if len(section) < 2:
            continue
        url = section[0].strip()
        rel = None
        for s in section[1:]:
            s = s.strip()
            if s.startswith('rel='):
                rel = s.split("=", 1)[1].strip().strip('"')
        if rel and url.startswith("<") and url.endswith(">"):
            links[rel] = url[1:-1]
    return links


def canvas_get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    r = requests.get(url, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r

def fetch_grade_change_events(
    base_url: str,
    course_id: int,
    assignment_id: int,
    student_id: int,
    start_time: dt.datetime,
    end_time: dt.datetime,
):
    """
    Try the Advanced query endpoint first:
      GET /api/v1/audit/grade_change (may 404 on some instances) :contentReference[oaicite:3]{index=3}
    Fallback to Course endpoint:
      GET /api/v1/audit/grade_change/courses/:course_id :contentReference[oaicite:4]{index=4}
    Then filter locally to assignment_id + student_id.
    """
    # --- 1) Try advanced query ---
    adv_url = f"{base_url}/api/v1/audit/grade_change"
    adv_params = {
        "course_id": course_id,
        "assignment_id": assignment_id,
        "student_id": student_id,
        "start_time": iso_z(start_time),
        "end_time": iso_z(end_time),
        "per_page": 100,
    }

    try:
        return _paged_grade_change_fetch(adv_url, adv_params)
    except requests.exceptions.HTTPError as e:
        # If advanced query isn't available, fall back to course endpoint
        if e.response is not None and e.response.status_code == 404:
            pass
        else:
            raise

    # --- 2) Fallback: course endpoint ---
    course_url = f"{base_url}/api/v1/audit/grade_change/courses/{course_id}"
    course_params = {
        "start_time": iso_z(start_time),
        "end_time": iso_z(end_time),
        "per_page": 100,
    }

    events, graders = _paged_grade_change_fetch(course_url, course_params)

    # Filter locally
    filtered = []
    for ev in events:
        links = ev.get("links") or {}
        # docs show links keys: assignment, course, student, grader :contentReference[oaicite:5]{index=5}
        if links.get("assignment") == assignment_id and links.get("student") == student_id:
            filtered.append(ev)

    return filtered, graders


def _paged_grade_change_fetch(url: str, params: dict):
    """
    Shared pagination fetcher for Grade Change Log endpoints.
    Returns (events, graders_by_id)
    """
    all_events = []
    graders = {}

    next_url = url
    next_params = params

    while next_url:
        resp = canvas_get(next_url, next_params)
        data = resp.json()

        events = data.get("events") if isinstance(data, dict) else None
        if events is None and isinstance(data, list):
            events = data
        if events:
            all_events.extend(events)

        if isinstance(data, dict):
            for g in data.get("graders", []) or []:
                gid = g.get("id")
                if isinstance(gid, int):
                    graders[gid] = g

        links = parse_link_header(resp.headers.get("Link", ""))
        if "next" in links:
            next_url = links["next"]
            next_params = None
        else:
            next_url = None

    return all_events, graders






def load_students(args) -> List[int]:
    ids: List[int] = []
    if args.students:
        for part in args.students.split(","):
            part = part.strip()
            if part:
                ids.append(int(part))
    if args.students_file:
        with open(args.students_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    ids.append(int(line))
    # dedupe while preserving order
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://grayson.instructure.com")
    ap.add_argument("--course", type=int, required=True, help="Canvas course_id")
    ap.add_argument("--assignment", type=int, required=True, help="Canvas assignment_id (the quiz's assignment)")
    ap.add_argument("--students", help="Comma-separated Canvas user_ids")
    ap.add_argument("--students-file", help="Text file with one Canvas user_id per line")
    ap.add_argument("--days", type=int, default=180, help="How far back to search (default 180 days)")
    ap.add_argument("--out", default="grade_change_audit.csv", help="CSV output filename")
    args = ap.parse_args()
    base_url = args.base_url.rstrip("/")

    #global CANVAS_BASE_URL
    CANVAS_BASE_URL = args.base_url.rstrip("/")

    student_ids = load_students(args)
    if not student_ids:
        print("ERROR: Provide --students or --students-file", file=sys.stderr)
        sys.exit(2)

    end_time = dt.datetime.now(dt.timezone.utc)
    start_time = end_time - dt.timedelta(days=args.days)

    rows = []
    for sid in student_ids:
        events, graders = fetch_grade_change_events(
            base_url=base_url,
            course_id=args.course,
            assignment_id=args.assignment,
            student_id=sid,
            start_time=start_time,
            end_time=end_time,
        )

        # Sort oldest -> newest so "first grade entered" is easy to see
        def event_time(e):
            return e.get("created_at") or ""
        events_sorted = sorted(events, key=event_time)

        for e in events_sorted:
            grader_id = e.get("grader_id")
            grader_name = None
            if isinstance(grader_id, int) and grader_id in graders:
                grader_name = graders[grader_id].get("name") or graders[grader_id].get("sortable_name")

            rows.append({
                "student_id": sid,
                "assignment_id": args.assignment,
                "course_id": args.course,
                "event_created_at": e.get("created_at"),
                "grade_before": e.get("grade_before"),
                "grade_after": e.get("grade_after"),
                "points_before": e.get("score_before"),
                "points_after": e.get("score_after"),
                "grader_id": grader_id,
                "grader_name": grader_name,
                "event_type": e.get("event_type"),
            })

    # Write CSV
    fieldnames = [
        "course_id", "assignment_id", "student_id",
        "event_created_at",
        "event_type",
        "points_before", "points_after",
        "grade_before", "grade_after",
        "grader_id", "grader_name",
    ]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {len(rows)} event(s) to {args.out}")
    print("Tip: sort/filter by student_id and event_created_at to see when the 50/50 was entered.")


if __name__ == "__main__":
    main()
