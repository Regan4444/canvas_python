#!/usr/bin/env python3
"""
Report one student's presence/participation in a single Canvas course over a date range.

Counts:
- Page views in the course (if permitted or unless --no-pageviews)
- Submitted assignments  (falls back gracefully if permissions block it)
- Discussion entries (posts + replies)

Also reports:
- Enrollment last_activity_at and total_activity_time as presence signals.

Enrollment search includes: active, inactive, completed, deleted.

Usage examples:
  python presence_one_student.py 12345 "Jane Doe" 2025-08-15 2025-08-27
  python presence_one_student.py 12345 "Jane Doe" 2025-08-15 2025-08-27 --no-pageviews
  python presence_one_student.py 12345 "Jane" 2025-08-15 2025-08-27 --user-id 58256

Prereqs:
  pip install requests python-dateutil
  Set env vars: CANVAS_BASE_URL, CANVAS_TOKEN   (or hard-code below)
"""

import argparse
import os
import sys
import time
from datetime import timezone
from dateutil import parser as dateparser
import requests

# -------------------------------------------------------------------
# Credentials
# -------------------------------------------------------------------
#BASE_URL = os.getenv("CANVAS_BASE_URL", "").rstrip("/")
#TOKEN = os.getenv("CANVAS_TOKEN", "")

# Option B (quick start): uncomment and fill if you prefer hard-coding
BASE_URL = "paste domain here"
TOKEN = "paste token here"

RATE_SLEEP = 0.15  # be kind to rate limits


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def require_creds():
    if not BASE_URL or not TOKEN:
        print("Please set CANVAS_BASE_URL and CANVAS_TOKEN, or hard-code BASE_URL and TOKEN in the script.")
        sys.exit(1)

def iso(dt_str: str) -> str:
    """Parse many date formats; return strict UTC ISO8601 with 'Z'."""
    dt = dateparser.parse(dt_str)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def api_get(path, params=None):
    """GET with pagination; returns list across pages (or an object if API returns one)."""
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    out = []
    while True:
        resp = requests.get(url, headers=headers, params=params)
        # Let the caller handle 401/403 if they want to fall back
        if resp.status_code in (401, 403):
            resp.raise_for_status()
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            out.extend(data)
        else:
            return data

        # pagination via Link header
        next_url = None
        link = resp.headers.get("Link", "")
        if link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
        if not next_url:
            break
        url = next_url
        params = None
        time.sleep(RATE_SLEEP)
    return out


# -------------------------------------------------------------------
# Data fetchers
# -------------------------------------------------------------------
def list_students_any_state(course_id):
    """Return students in active, inactive, completed, or deleted states."""
    params = {
        "type[]": "StudentEnrollment",
        "state[]": "active",
        "state[]": "inactive",
        "state[]": "completed",
        "state[]": "deleted",
        "per_page": 100,
        "include[]": "user",
    }
    enrollments = api_get(f"/api/v1/courses/{course_id}/enrollments", params)
    students = []
    for e in enrollments:
        u = e.get("user") or {}
        students.append({
            "user_id": u.get("id"),
            "name": u.get("name"),
            "login_id": u.get("login_id"),
            "email": u.get("email"),
            "enrollment_state": e.get("enrollment_state"),
        })
    return students

def get_enrollment_activity(course_id, user_id):
    """
    Get a single student's enrollment record (any state) for this course.
    Returns (enrollment_state, last_activity_at, total_activity_time)
    """
    params = {
        "type[]": "StudentEnrollment",
        "user_id": user_id,
        "state[]": "active",
        "state[]": "inactive",
        "state[]": "completed",
        "state[]": "deleted",
        "per_page": 50,
    }
    try:
        enrollments = api_get(f"/api/v1/courses/{course_id}/enrollments", params)
    except requests.HTTPError as err:
        print(f"[Warning] Could not read enrollment activity for user {user_id}: {err}")
        return None, None, None

    # pick the first enrollment matching user (there should be at most one per course)
    for e in enrollments:
        if (e.get("user") or {}).get("id") == user_id:
            return (
                e.get("enrollment_state"),
                e.get("last_activity_at"),      # e.g., "2025-08-20T18:22:11Z"
                e.get("total_activity_time"),   # seconds
            )
    return None, None, None

def list_discussion_topics(course_id):
    params = {"only_announcements": "false", "per_page": 100}
    return api_get(f"/api/v1/courses/{course_id}/discussion_topics", params)

def count_user_page_views(user_id, course_id, start_iso, end_iso):
    """Requires permission to read Page Views. Filters by course context."""
    params = {
        "start_time": start_iso,
        "end_time": end_iso,
        "context_type": "Course",
        "context_id": course_id,
        "per_page": 100,
    }
    views = api_get(f"/api/v1/users/{user_id}/page_views", params)
    return len([v for v in views if str(v.get("context_id")) == str(course_id)])

def count_user_submissions(course_id, user_id, start_iso, end_iso):
    """
    Count submissions whose submitted_at fall within the window.
    Gracefully returns 0 if the Submissions API is forbidden (403).
    """
    params = {
        "student_ids[]": user_id,
        "per_page": 100,
        "submitted_since": start_iso,
        "workflow_state[]": "submitted",
        "include[]": "submission_history",
    }
    try:
        submissions = api_get(f"/api/v1/courses/{course_id}/students/submissions", params)
    except requests.HTTPError as err:
        if err.response is not None and err.response.status_code == 403:
            print("[Warning] Submissions API is forbidden (likely grade/submission-view permission).")
            print("          Continuing without submission counts.\n")
            return 0
        raise

    end_dt = dateparser.parse(end_iso)
    count = 0
    for sub in submissions:
        ts = sub.get("submitted_at")
        if ts:
            sdt = dateparser.parse(ts)
            if sdt <= end_dt:
                count += 1
                continue
        for hist in sub.get("submission_history") or []:
            ts2 = hist.get("submitted_at")
            if ts2 and (start_iso <= iso(ts2) <= end_iso):
                count += 1
                break
    return count

def count_user_discussion_entries(course_id, user_id, start_iso, end_iso, topics_cache=None):
    topics = topics_cache or list_discussion_topics(course_id)
    total = 0
    start_dt = dateparser.parse(start_iso)
    end_dt = dateparser.parse(end_iso)
    for t in topics:
        topic_id = t["id"]
        entries = api_get(f"/api/v1/courses/{course_id}/discussion_topics/{topic_id}/entries",
                          {"per_page": 100})
        for e in entries:
            if e.get("user_id") == user_id:
                ts = e.get("created_at")
                if ts:
                    dt = dateparser.parse(ts)
                    if start_dt <= dt <= end_dt:
                        total += 1
            for r in e.get("recent_replies") or []:
                if r.get("user_id") == user_id:
                    ts2 = r.get("created_at")
                    if ts2:
                        dt2 = dateparser.parse(ts2)
                        if start_dt <= dt2 <= end_dt:
                            total += 1
        time.sleep(RATE_SLEEP)
    return total


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Canvas one-student presence/participation report")
    p.add_argument("course_id", help="Canvas course ID")
    p.add_argument("student_name_part", help="Student name (partial match, case-insensitive)")
    p.add_argument("start_date", help="Start date (e.g., 2025-08-15 or 2025-08-15T00:00:00Z)")
    p.add_argument("end_date", help="End date (e.g., 2025-08-27 or 2025-08-27T23:59:59Z)")
    p.add_argument("--no-pageviews", action="store_true",
                   help="Skip page views (use if you lack permission or want speed)")
    p.add_argument("--user-id", type=int, default=None,
                   help="Bypass name search and use an exact Canvas user_id")
    return p.parse_args()

def main():
    require_creds()
    args = parse_args()

    course_id = args.course_id
    start = iso(args.start_date)
    end = iso(args.end_date)

    # Resolve user_id (either directly or via name match across ANY enrollment state)
    if args.user_id:
        user_id = args.user_id
        student_meta = {"name": "(resolved by --user-id)", "login_id": None, "email": None, "enrollment_state": "unknown"}
    else:
        name_query = args.student_name_part.lower()
        students = list_students_any_state(course_id)
        matches = [s for s in students if name_query in (s.get("name") or "").lower()]
        if not matches:
            print(f"No student matching '{name_query}' found in course {course_id} (any enrollment state).")
            sys.exit(1)
        if len(matches) > 1:
            print("Multiple matches; refine your name or use --user-id. Matches:")
            for s in matches:
                print(f" - {s.get('name')} | login: {s.get('login_id')} | user_id: {s.get('user_id')} | state: {s.get('enrollment_state')}")
            sys.exit(1)
        s = matches[0]
        user_id = s["user_id"]
        student_meta = s

    # Pull enrollment-level activity as a fallback presence signal
    enr_state, last_activity_at, total_activity_time = get_enrollment_activity(course_id, user_id)

    print(f"\nAnalyzing {student_meta.get('name')} (user_id={user_id}, state={student_meta.get('enrollment_state') or enr_state})")
    print(f"Course {course_id} | Window {start} to {end}\n")

    topics_cache = list_discussion_topics(course_id)

    # Page Views: safe-by-default. Try unless --no-pageviews is set; never break the run.
    pv = 0
    if not args.no_pageviews:
        try:
            pv = count_user_page_views(user_id, course_id, start, end)
        except requests.HTTPError as err:
            print("[Warning] Page views unavailable (permission/scope). Continuing without them.")
            print(f"Details: {err}\n")
            pv = 0

    subs = count_user_submissions(course_id, user_id, start, end)  # returns 0 if forbidden
    disc = count_user_discussion_entries(course_id, user_id, start, end, topics_cache)

    # Presence logic:
    # - activity if any of: pageviews>0, submissions>0, discussion>0, or enrollment activity within window
    present_from_enrollment = False
    if last_activity_at:
        try:
            ladt = dateparser.parse(last_activity_at)
            present_from_enrollment = (dateparser.parse(start) <= ladt <= dateparser.parse(end))
        except Exception:
            present_from_enrollment = False

    present = (pv > 0) or (subs > 0) or (disc > 0) or present_from_enrollment or (total_activity_time or 0) > 0
    participated = (subs > 0) or (disc > 0)

    print("--------------- RESULT ---------------")
    print(f"Student:              {student_meta.get('name')}  | login: {student_meta.get('login_id')}  | email: {student_meta.get('email')}")
    print(f"Enrollment state:     {student_meta.get('enrollment_state') or enr_state}")
    print(f"Page Views:           {pv} {'(skipped)' if args.no_pageviews else ''}")
    print(f"Submissions:          {subs} {'(permissions blocked → counted as 0)' if subs == 0 else ''}")
    print(f"Discussion posts:     {disc}")
    print(f"Last activity (enr):  {last_activity_at}")
    print(f"Total activity secs:  {total_activity_time}")
    print("--------------------------------------")
    print(f"Present?              {'YES' if present else 'NO'}")
    print(f"Participated?         {'YES' if participated else 'NO'}")
    print("--------------------------------------\n")

if __name__ == "__main__":
    main()

