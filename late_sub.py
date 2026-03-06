#!/usr/bin/env python3
"""
AssignmentSubmissions.py

Purpose:
    For a given Canvas course and a single assignment, list each student
    (active, inactive, concluded), whether they turned it in, WHEN they turned
    it in, whether it was late, and their enrollment state.

Output:
    - Pretty console table
    - assignment_submissions.csv in the same folder

Setup:
    1. Fill in CANVAS_BASE_URL and TOKEN below.
    2. Fill in COURSE_ID and ASSIGNMENT_ID below.
"""

import csv
import datetime
import requests
from typing import Iterator, Dict, Any, List, Optional, Tuple


# ========= USER CONFIG (edit these 4) =========
CANVAS_BASE_URL = "https://grayson.instructure.com"  # <-- no trailing slash
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"                     # <-- your token
COURSE_ID = 43637                                    # <-- course numeric ID
ASSIGNMENT_ID = 856315                               # <-- assignment numeric ID
# ==============================================


# --- helper: auth session with pagination ---
class CanvasClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}"
        })

    def get_paginated(self, path: str, params: Dict[str, Any] | None = None) -> Iterator[Dict[str, Any]]:
        """
        Yields each item across all pages for a Canvas API endpoint
        that returns a JSON array and uses Link headers for pagination.
        """
        url = self.base_url + path
        first = True
        while url:
            resp = self.session.get(url, params=params if first else None)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for row in data:
                    yield row
            else:
                yield data
                break

            # parse Link header for rel="next"
            link = resp.headers.get("Link", "")
            next_url = None
            if link:
                parts = link.split(",")
                for p in parts:
                    segs = p.split(";")
                    if len(segs) >= 2:
                        url_part = segs[0].strip()
                        rel_part = segs[1].strip()
                        if rel_part == 'rel="next"':
                            if url_part.startswith("<") and url_part.endswith(">"):
                                next_url = url_part[1:-1]
            url = next_url
            first = False

    def get_raw(self, path: str, params: Dict[str, Any] | None = None) -> requests.Response:
        """
        Low-level GET (no raise_for_status yet, we handle it ourselves).
        """
        url = self.base_url + path
        resp = self.session.get(url, params=params)
        return resp

    def get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        """
        High-level GET that raises for status automatically.
        """
        url = self.base_url + path
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def list_students_all_states(client: CanvasClient, course_id: int) -> List[Dict[str, Any]]:
    """
    Return one row per unique user, including active, inactive, and concluded
    student enrollments.

    We'll also capture their enrollment_state ('active', 'inactive', 'concluded')
    so we can report it later.
    """
    students: Dict[int, Dict[str, Any]] = {}

    path = f"/api/v1/courses/{course_id}/enrollments"
    params = {
        "type[]": "StudentEnrollment",
        # include multiple states so we see inactive/concluded students
        "state[]": ["active", "inactive", "concluded"],
        "per_page": 100
    }

    for enr in client.get_paginated(path, params=params):
        user = enr.get("user", {})
        uid = user.get("id")
        if uid is None:
            continue

        enrollment_state = enr.get("enrollment_state") or enr.get("user", {}).get("enrollments", None)
        # Canvas usually gives "enrollment_state": "active", "inactive", or "completed".
        # "completed" is effectively "concluded". We'll normalize that.
        if isinstance(enrollment_state, str):
            if enrollment_state == "completed":
                enrollment_state_norm = "concluded"
            else:
                enrollment_state_norm = enrollment_state
        else:
            # fallback if weird
            enrollment_state_norm = enr.get("state") or "unknown"

        # If we already saw this user, prefer an "active" state over inactive/concluded,
        # but otherwise don't lose info.
        existing = students.get(uid)
        if existing:
            # rank: active > inactive > concluded > everything else
            rank = {"active": 3, "inactive": 2, "concluded": 1}
            old_rank = rank.get(existing["enrollment_state"], 0)
            new_rank = rank.get(enrollment_state_norm, 0)
            if new_rank > old_rank:
                existing["enrollment_state"] = enrollment_state_norm
        else:
            students[uid] = {
                "id": uid,
                "name": user.get("name"),
                "sortable_name": user.get("sortable_name"),
                "sis_user_id": user.get("sis_user_id"),
                "enrollment_state": enrollment_state_norm,
            }

    return list(students.values())


def get_assignment_details(client: CanvasClient, course_id: int, assignment_id: int) -> Dict[str, Any]:
    """
    Try to fetch assignment metadata (to get the due_at timestamp).

    We first try with include[], then retry plain if Canvas rejects it.
    If both fail, we return a dict with 'due_at': None so the script won't crash.
    """
    path = f"/api/v1/courses/{course_id}/assignments/{assignment_id}"

    params_rich = {
        "include[]": ["submission", "assignment_visibility", "overrides"]
    }
    resp = client.get_raw(path, params=params_rich)
    if resp.status_code == 200:
        return resp.json()

    resp2 = client.get_raw(path, params=None)
    if resp2.status_code == 200:
        return resp2.json()

    print(f"⚠ Could not fetch assignment details (status {resp.status_code}/{resp2.status_code}).")
    return {"due_at": None}


def get_submission_for_student(
    client: CanvasClient,
    course_id: int,
    assignment_id: int,
    user_id: int
) -> Dict[str, Any]:
    """
    Fetch a single student's submission object for the assignment.
    We'll retry without extra include[] if Canvas doesn't like it.
    """
    path = f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}"
    params = {
        "include[]": ["submission_history", "rubric_assessment", "full_rubric_assessment"]
    }

    resp = client.get_raw(path, params=params)
    if resp.status_code == 200:
        return resp.json()

    resp2 = client.get_raw(path, params=None)
    if resp2.status_code == 200:
        return resp2.json()

    print(f"⚠ Could not fetch submission for user {user_id} (status {resp.status_code}/{resp2.status_code}).")
    return {
        "workflow_state": None,
        "score": None,
        "grade": None,
        "submitted_at": None,
        "graded_at": None,
    }


def parse_canvas_time(
    ts: Optional[str]
) -> Tuple[Optional[str], Optional[str], Optional[datetime.datetime]]:
    """
    Convert Canvas ISO8601 UTC ('2025-10-29T14:32:11Z') into:
        - raw_ts
        - human "MM/DD/YYYY HH:MM (CT approx)"
        - datetime (UTC) for math
    """
    if not ts:
        return None, None, None

    if ts.endswith("Z"):
        ts_clean = ts[:-1]
        dt_utc = datetime.datetime.fromisoformat(ts_clean).replace(tzinfo=datetime.timezone.utc)
    else:
        dt_utc = datetime.datetime.fromisoformat(ts)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=datetime.timezone.utc)

    # convert to rough Central Time (no DST logic here, just UTC-5)
    central_offset = datetime.timedelta(hours=-5)
    dt_cent = dt_utc.astimezone(datetime.timezone(central_offset))
    human = dt_cent.strftime("%m/%d/%Y %H:%M") + " (CT approx)"

    return ts, human, dt_utc


def is_late(
    submitted_dt_utc: Optional[datetime.datetime],
    due_dt_utc: Optional[datetime.datetime]
) -> str:
    """
    Return "late" if submitted_dt_utc is after due_dt_utc.
    Else "".
    If either timestamp is missing, "".
    """
    if submitted_dt_utc and due_dt_utc:
        if submitted_dt_utc > due_dt_utc:
            return "late"
    return ""


def build_report_rows(
    client: CanvasClient,
    course_id: int,
    assignment_id: int
) -> List[Dict[str, Any]]:
    """
    1. Grab assignment due date.
    2. Get all (active/inactive/concluded) student enrollments.
    3. For each student, get submission, compare times, build row.
    """
    assignment = get_assignment_details(client, course_id, assignment_id)
    due_raw, due_local, due_dt_utc = parse_canvas_time(assignment.get("due_at"))

    students = list_students_all_states(client, course_id)

    rows: List[Dict[str, Any]] = []
    for stu in students:
        sub = get_submission_for_student(client, course_id, assignment_id, stu["id"])

        workflow_state = sub.get("workflow_state")  # 'submitted', 'graded', 'missing', etc.
        score = sub.get("score")
        grade = sub.get("grade")

        submitted_at_raw, submitted_at_local, submitted_dt_utc = parse_canvas_time(
            sub.get("submitted_at")
        )
        graded_at_raw, graded_at_local, _graded_dt_utc = parse_canvas_time(
            sub.get("graded_at")
        )

        late_flag = is_late(submitted_dt_utc, due_dt_utc)

        row = {
            "user_id": stu.get("id"),
            "sis_user_id": stu.get("sis_user_id"),
            "student_name": stu.get("name"),
            "enrollment_state": stu.get("enrollment_state"),
            "status": workflow_state,
            "assignment_due_at_utc": due_raw,
            "assignment_due_at_local_ct": due_local,
            "submitted_at_utc": submitted_at_raw,
            "submitted_at_local_ct": submitted_at_local,
            "late": late_flag,
            "graded_at_utc": graded_at_raw,
            "graded_at_local_ct": graded_at_local,
            "score": score,
            "grade": grade
        }
        rows.append(row)

    return rows


def write_csv(rows: List[Dict[str, Any]], filename: str = "assignment_submissions.csv") -> None:
    """
    Dump rows to CSV.
    """
    if not rows:
        print("No rows to write.")
        return

    fieldnames = [
        "user_id",
        "sis_user_id",
        "student_name",
        "enrollment_state",
        "status",
        "assignment_due_at_utc",
        "assignment_due_at_local_ct",
        "submitted_at_utc",
        "submitted_at_local_ct",
        "late",
        "graded_at_utc",
        "graded_at_local_ct",
        "score",
        "grade",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"💾 Wrote {len(rows)} rows to {filename}")


def print_table(rows: List[Dict[str, Any]]) -> None:
    """
    Console view. Shows enrollment_state so you know why someone is still showing up.
    """
    if not rows:
        print("No data.")
        return

    due_local = rows[0].get("assignment_due_at_local_ct") or "N/A"

    print("")
    print("Assignment Submission Report")
    print("=" * 110)
    print(f"Due: {due_local}")
    print("")
    headers = [
        "Student Name",
        "Enroll",
        "Status",
        "Submitted (CT approx)",
        "Late?",
        "Score",
    ]
    print(f"{headers[0]:33} {headers[1]:8} {headers[2]:12} {headers[3]:22} {headers[4]:6} {headers[5]:>6}")
    print("-" * 110)

    for r in rows:
        name = (r["student_name"] or "")[:33]
        enroll_state = (r["enrollment_state"] or "")[:8]
        status = (r["status"] or "")[:12]
        sub_local = (r["submitted_at_local_ct"] or "—")[:22]
        late_flag = (r["late"] or "")[:6]
        score = "" if r["score"] is None else str(r["score"])

        print(f"{name:33} {enroll_state:8} {status:12} {sub_local:22} {late_flag:6} {score:>6}")

    print("=" * 110)
    print("Enroll column: active / inactive / concluded (completed).")
    print("Status column: submitted, graded, missing, unsubmitted, excused, etc.")
    print('"Late?" = "late" if submitted after the due date (UTC compare).')
    print("Blank late = on time OR no submission.")
    print("Times labeled CT approx = UTC converted with a fixed -5 offset (no DST logic).")
    print("")


def main():
    client = CanvasClient(CANVAS_BASE_URL, TOKEN)

    print(f"🔐 Using Canvas at {CANVAS_BASE_URL}")
    print(f"📘 Course ID: {COURSE_ID}")
    print(f"📝 Assignment ID: {ASSIGNMENT_ID}")
    print("🔎 Gathering roster (active+inactive+concluded), assignment details, and submissions...")

    rows = build_report_rows(client, COURSE_ID, ASSIGNMENT_ID)

    write_csv(rows)
    print_table(rows)


if __name__ == "__main__":
    main()
