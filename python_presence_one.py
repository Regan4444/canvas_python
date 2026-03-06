#!/usr/bin/env python3

#-----------------------------------
#The script's purpose is to determine if a student was in a specific course over a 
#specific range of time.
#usage is  python python_presence_one.py <COURSE_ID> <STUDENT_NAME> <START_DATE> <END_DATE>
#------------------------------------
import os
import sys
import time
from datetime import datetime, timezone
from dateutil import parser as dateparser
import requests

BASE_URL = "https://grayson.instructure.com/"
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
RATE_SLEEP = 0.15

def iso(dt_str):
    dt = dateparser.parse(dt_str)
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def api_get(path, params=None):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    out = []
    while True:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            out.extend(data)
        else:
            return data
        # pagination
        link = resp.headers.get("Link", "")
        next_url = None
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

def list_students_any_state(course_id):
    # https://canvas.instructure.com/doc/api/enrollments.html#method.enrollments_api.index
    params = {
        "type[]": "StudentEnrollment",
        # pull every relevant state
        "state[]": "active",
        "state[]": "inactive",
        "state[]": "completed",
        "state[]": "deleted",
        "per_page": 100,
        "include[]": "user"
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
            "enrollment_state": e.get("enrollment_state"),  # active/inactive/completed/deleted
        })
    return students

def count_user_page_views(user_id, course_id, start_iso, end_iso):
    params = {
        "start_time": start_iso,
        "end_time": end_iso,
        "context_type": "Course",
        "context_id": course_id,
        "per_page": 100
    }
    views = api_get(f"/api/v1/users/{user_id}/page_views", params)
    return len([v for v in views if str(v.get("context_id")) == str(course_id)])

def main():
    if not BASE_URL or not TOKEN:
        print("Please set CANVAS_BASE_URL and CANVAS_TOKEN environment variables.")
        sys.exit(1)
    if len(sys.argv) < 5:
        print("Usage: python presence_one.py <COURSE_ID> <STUDENT_NAME> <START_DATE> <END_DATE>")
        sys.exit(1)

    course_id = sys.argv[1]
    student_name = sys.argv[2].lower()
    start_iso = iso(sys.argv[3])
    end_iso = iso(sys.argv[4])

    students = list_students_any_state(course_id)
    # match student by name substring
    target = [s for s in students if student_name in (s["name"] or "").lower()]

    if not target:
        print(f"No student found matching '{student_name}' in course {course_id}")
        sys.exit(1)
    elif len(target) > 1:
        print("Multiple matches found, refine your search:")
        for s in target:
            print(f" - {s['name']} ({s['login_id']})")
        sys.exit(1)

    student = target[0]
    print(f"Checking {student['name']} in course {course_id} between {start_iso} and {end_iso}...")

    pv = count_user_page_views(student["user_id"], course_id, start_iso, end_iso)

    print("------------------------------------------------")
    print(f"Student: {student['name']} ({student['login_id']})")
    print(f"Email:   {student['email']}")
    print(f"Page Views in course: {pv}")
    print("------------------------------------------------")

if __name__ == "__main__":
    main()
