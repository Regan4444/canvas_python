#!/usr/bin/env python3
"""
canvas_when_grade_entered.py

Shows when a grade was ENTERED/CHANGED for a specific student in a specific course+assignment.
Pulls BOTH:
  1) Grade Change Log (Audit) events (most authoritative for "changed when / by whom")
  2) Submission details (graded_at, score, grader_id)

Usage:
  python canvas_when_grade_entered.py --course-id 44413 --assignment-id 123456 --student-id 69772 --days-back 365
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

# -----------------------------
# HARD-CODE THESE
# -----------------------------
CANVAS_DOMAIN = "paste domain here"
CANVAS_TOKEN = "paste token here"

CENTRAL_TZ = ZoneInfo("America/Chicago")

def parse_canvas_dt(dt_str: str) -> datetime:
    if not dt_str:
        raise ValueError("Empty datetime string")
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)

def utc_to_central(dt_utc: datetime) -> datetime:
    if dt_utc.tzinfo is None:
        raise ValueError("Need tz-aware datetime")
    return dt_utc.astimezone(CENTRAL_TZ)

def dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Need tz-aware datetime")
    return dt.isoformat()

def canvas_get(url: str, params=None):
    headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"}
    r = requests.get(url, headers=headers, params=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:800]}")
    return r.json(), r.headers

def canvas_get_paginated(url: str, params=None, max_pages: int = 200):
    headers = {"Authorization": f"Bearer {CANVAS_TOKEN}"}
    page = 0
    while url and page < max_pages:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:800]}")
        data = r.json()
        yield data

        # pagination
        link = r.headers.get("Link", "")
        next_url = None
        if link:
            for part in [p.strip() for p in link.split(",")]:
                if 'rel="next"' in part:
                    start = part.find("<") + 1
                    end = part.find(">")
                    if start > 0 and end > start:
                        next_url = part[start:end]
                    break
        url = next_url
        params = None
        page += 1

def fetch_submission(course_id: int, assignment_id: int, student_id: int):
    # Submission endpoint (includes graded_at, grader_id, score, etc.)
    url = f"{CANVAS_DOMAIN}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{student_id}"
    params = {
        "include[]": [
            "submission_history",   # helpful if multiple attempts/grades
            "rubric_assessment",
            "visibility",
            "user"
        ]
    }
    data, _ = canvas_get(url, params=params)
    return data

def fetch_grade_change_events(course_id: int, assignment_id: int, student_id: int,
                             start_time: datetime, end_time: datetime):
    # Grade Change Log (Audit) for course
    url = f"{CANVAS_DOMAIN}/api/v1/audit/grade_change/courses/{course_id}"
    params = {
        "start_time": dt_to_iso(start_time),
        "end_time": dt_to_iso(end_time),
    }

    matches = []
    for page_data in canvas_get_paginated(url, params=params):
        # Audit endpoint might return list OR compound dict. Handle both.
        if isinstance(page_data, dict) and "events" in page_data:
            items = page_data.get("events") or []
        elif isinstance(page_data, list):
            items = page_data
        else:
            items = []

        for ev in items:
            ev_student_id = ev.get("student_id") or ev.get("user_id")
            ev_assignment_id = ev.get("assignment_id")
            ev_course_id = ev.get("course_id")

            if ev_course_id is not None and int(ev_course_id) != int(course_id):
                continue
            if ev_student_id is None or int(ev_student_id) != int(student_id):
                continue
            if ev_assignment_id is None or int(ev_assignment_id) != int(assignment_id):
                continue

            matches.append(ev)

    def event_dt(ev):
        t = ev.get("created_at") or ev.get("event_time") or ev.get("timestamp")
        try:
            return parse_canvas_dt(t).astimezone(timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    matches.sort(key=event_dt, reverse=True)
    return matches

def format_dt_pair(dt_str: str):
    if not dt_str:
        return "(none)", "(none)"
    try:
        dt_utc = parse_canvas_dt(dt_str).astimezone(timezone.utc)
        dt_ct = utc_to_central(dt_utc)
        return dt_utc.isoformat(), dt_ct.isoformat()
    except Exception:
        return f"(unparsed) {dt_str}", f"(unparsed) {dt_str}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course-id", type=int, required=True)
    ap.add_argument("--assignment-id", type=int, required=True)
    ap.add_argument("--student-id", type=int, required=True)
    ap.add_argument("--days-back", type=int, default=365)
    ap.add_argument("--drop-date", type=str, default=None,
                    help="Optional: drop date/time in Central, e.g. '2026-02-02 17:00' (24h).")
    args = ap.parse_args()

    if "PASTE_YOUR_TOKEN_HERE" in CANVAS_TOKEN:
        print("ERROR: Paste your Canvas token into CANVAS_TOKEN in the script.")
        sys.exit(2)

    # Optional drop date parse (assumed Central)
    drop_dt_ct = None
    if args.drop_date:
        # Expect: YYYY-MM-DD HH:MM
        try:
            drop_dt_ct = datetime.strptime(args.drop_date, "%Y-%m-%d %H:%M").replace(tzinfo=CENTRAL_TZ)
        except ValueError:
            print("ERROR: --drop-date must be like '2026-02-02 17:00'")
            sys.exit(2)

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=args.days_back)

    print("\n=== Submission record (often shows when it was graded) ===")
    try:
        sub = fetch_submission(args.course_id, args.assignment_id, args.student_id)
        graded_at = sub.get("graded_at")
        submitted_at = sub.get("submitted_at")
        score = sub.get("score")
        grade = sub.get("grade")
        grader_id = sub.get("grader_id")
        late = sub.get("late")
        missing = sub.get("missing")

        graded_utc, graded_ct = format_dt_pair(graded_at)
        subm_utc, subm_ct = format_dt_pair(submitted_at)

        print(f"Current score/grade: {score} / {grade}")
        print(f"grader_id: {grader_id}")
        print(f"submitted_at (UTC / CT): {subm_utc} / {subm_ct}")
        print(f"graded_at    (UTC / CT): {graded_utc} / {graded_ct}")
        print(f"flags: late={late}, missing={missing}")

        if drop_dt_ct and graded_at:
            try:
                g_ct = utc_to_central(parse_canvas_dt(graded_at).astimezone(timezone.utc))
                status = "AFTER" if g_ct > drop_dt_ct else "BEFORE/ON"
                print(f"Drop date (CT): {drop_dt_ct.isoformat()} -> graded_at is {status} drop date")
            except Exception:
                pass

    except Exception as e:
        print(f"FAILED to fetch submission: {e}")

    print("\n=== Grade Change Log (audit) events (authoritative for ‘entered/changed when’) ===")
    try:
        events = fetch_grade_change_events(
            course_id=args.course_id,
            assignment_id=args.assignment_id,
            student_id=args.student_id,
            start_time=start_time,
            end_time=end_time,
        )

        if not events:
            print("No matching grade-change audit events found in this date window.")
            print("Notes:")
            print("- Try increasing --days-back")
            print("- If the 0 was never actually ‘entered’ (e.g., instructor views as 0 via policy), there may be no audit event.")
            return

        print(f"Found {len(events)} event(s). Newest first:\n")
        for i, ev in enumerate(events[:30], start=1):
            raw_time = ev.get("created_at") or ev.get("event_time") or ev.get("timestamp")
            utc_str, ct_str = format_dt_pair(raw_time)

            old_score = ev.get("old_score")
            new_score = ev.get("new_score")
            old_grade = ev.get("old_grade")
            new_grade = ev.get("new_grade")
            grader_id = ev.get("grader_id")

            print(f"{i}. time (UTC / CT): {utc_str} / {ct_str}")
            print(f"   grader_id: {grader_id}")
            if old_score is not None or new_score is not None:
                print(f"   score: {old_score} -> {new_score}")
            if old_grade is not None or new_grade is not None:
                print(f"   grade: {old_grade} -> {new_grade}")

            if drop_dt_ct:
                try:
                    ev_ct = utc_to_central(parse_canvas_dt(raw_time).astimezone(timezone.utc))
                    status = "AFTER" if ev_ct > drop_dt_ct else "BEFORE/ON"
                    print(f"   vs drop date: {status} (drop date CT: {drop_dt_ct.isoformat()})")
                except Exception:
                    pass
            print("")

        # Most recent change:
        latest = events[0]
        latest_time = latest.get("created_at") or latest.get("event_time") or latest.get("timestamp")
        l_utc, l_ct = format_dt_pair(latest_time)
        print("Most recent grade-change event time:")
        print(f"  UTC: {l_utc}")
        print(f"  CT:  {l_ct}")

    except Exception as e:
        print(f"FAILED to fetch grade-change audit events: {e}")
        sys.exit(1)

if __name__ == "__main__":

    main()
