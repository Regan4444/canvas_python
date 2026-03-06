import csv
import datetime as dt
import time
import requests

#----------------------------
#The purpose of the script is to audit the login time for a user to determine how much time is spent
#logged into Canvas.
#----------------------------

# ---------------------------
# Hardcoded Canvas settings
# ---------------------------

BASE_URL = "https://grayson.instructure.com"       # your Canvas domain
ACCESS_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"            # replace with your Canvas API token
USER_ID = "15368"                                  # numeric Canvas user ID
START_TIME = "2025-08-01T00:00:00Z"                # ISO 8601 UTC start time
END_TIME = "2025-10-23T23:59:59Z"                  # ISO 8601 UTC end time
SESSION_GAP_MINUTES = 30                           # gap threshold to infer new session

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

def parse_iso(s):
    if s.endswith("Z"):
        return dt.datetime.strptime(s, ISO_FMT)
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)

def iso(d):
    return d.strftime(ISO_FMT)

def clamp(created_at, start, end):
    try:
        t = parse_iso(created_at)
    except Exception:
        return False
    return start <= t <= end

def backoff_sleep(attempt):
    time.sleep(min(2 ** attempt, 10))

class CanvasClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def get(self, path, params=None):
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        attempts = 0
        while True:
            try:
                resp = self.session.get(url, params=params, timeout=60)
                if resp.status_code == 429:
                    time.sleep(int(resp.headers.get("Retry-After", "1")))
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException:
                attempts += 1
                if attempts >= 5:
                    raise
                backoff_sleep(attempts)

    def get_paginated(self, path, params=None):
        url = f"{self.base_url}{path}"
        while url:
            resp = self.get(url, params=params)
            params = None  # only first request uses params
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    yield item
            else:
                for item in data.get("data", []):
                    yield item
            link = resp.headers.get("Link", "")
            url = None
            if link and 'rel="next"' in link:
                parts = [p.strip() for p in link.split(",")]
                for p in parts:
                    if 'rel="next"' in p:
                        url = p[p.find("<")+1:p.find(">")]
                        break

# ---------- Page views & sessions ----------

def fetch_page_views(client, user_id, start, end):
    params = {"start_time": iso(start), "end_time": iso(end), "per_page": 100}
    path = f"/api/v1/users/{user_id}/page_views"
    views = list(client.get_paginated(path, params))
    return [v for v in views if clamp(v.get("created_at", ""), start, end)]

def infer_sessions(page_views, gap_minutes=30):
    if not page_views:
        return []
    pvs = sorted(page_views, key=lambda v: parse_iso(v["created_at"]))
    sessions = []
    start = parse_iso(pvs[0]["created_at"])
    last = start
    for v in pvs[1:]:
        t = parse_iso(v["created_at"])
        if (t - last) > dt.timedelta(minutes=gap_minutes):
            sessions.append({
                "session_start": iso(start),
                "session_end": iso(last),
                "duration_minutes": round((last - start).total_seconds() / 60, 1)
            })
            start = t
        last = t
    sessions.append({
        "session_start": iso(start),
        "session_end": iso(last),
        "duration_minutes": round((last - start).total_seconds() / 60, 1)
    })
    return sessions

# ---------- Enrollments & per-course submissions ----------

def fetch_student_enrollments(client, user_id):
    """
    Returns {course_id: course_name} for the user's active Student enrollments you can see.
    """
    params = {
        "per_page": 100,
        "type[]": ["StudentEnrollment"],
        "state[]": ["active","invited","current_and_invited"]  # be generous
        # You can also add include[]=course if enabled; not required.
    }
    path = f"/api/v1/users/{user_id}/enrollments"
    enrollments = list(client.get_paginated(path, params))
    course_map = {}
    for e in enrollments:
        cid = e.get("course_id")
        # Course name may not be embedded; we’ll try a lightweight fetch if missing later
        name = (e.get("course", {}) or {}).get("name")
        course_map[cid] = name
    return course_map

def fetch_course_name(client, course_id):
    try:
        resp = client.get(f"/api/v1/courses/{course_id}")
        return resp.json().get("name")
    except Exception:
        return None

def fetch_submissions_per_course(client, user_id, course_id, start, end, course_name=None):
    """
    Uses the per-course endpoint:
      GET /api/v1/courses/:course_id/students/submissions?student_ids[]=USER_ID
    """
    params = {
        "per_page": 100,
        "student_ids[]": [user_id],
        "include[]": ["assignment"]  # course is known; attach name ourselves
    }
    path = f"/api/v1/courses/{course_id}/students/submissions"
    try:
        subs = list(client.get_paginated(path, params))
    except requests.HTTPError as e:
        # Skip courses we can't read in this context
        print(f"  (skip) course {course_id}: {e}")
        return []

    out = []
    for s in subs:
        submitted = s.get("submitted_at") or s.get("graded_at") or s.get("updated_at")
        if not submitted or not clamp(submitted, start, end):
            continue
        assignment = s.get("assignment", {}) or {}
        out.append({
            "course_id": course_id,
            "course_name": course_name,
            "assignment_id": s.get("assignment_id") or assignment.get("id"),
            "assignment_name": assignment.get("name"),
            "attempt": s.get("attempt"),
            "submitted_at": s.get("submitted_at"),
            "graded_at": s.get("graded_at"),
            "score": s.get("score"),
            "workflow_state": s.get("workflow_state"),
            "late": s.get("late"),
            "excused": s.get("excused"),
            "missing": s.get("missing"),
            "submission_type": s.get("submission_type"),
            "entered_grade": s.get("entered_grade"),
            "preview_url": s.get("preview_url"),
        })
    return out

def fetch_all_submissions(client, user_id, start, end):
    course_map = fetch_student_enrollments(client, user_id)
    results = []
    for cid, cname in course_map.items():
        if not cid:
            continue
        # Ensure we have a course name if possible
        if not cname:
            cname = fetch_course_name(client, cid)
        print(f"  • Fetching submissions in course {cid} ({cname or 'unknown'}) ...")
        results.extend(fetch_submissions_per_course(client, user_id, cid, start, end, cname))
    return results

# ---------- CSV helpers ----------

def write_csv(path, rows, headers):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

# ---------- Main ----------

def main():
    start = parse_iso(START_TIME)
    end = parse_iso(END_TIME)
    client = CanvasClient(BASE_URL, ACCESS_TOKEN)

    print("Fetching page views…")
    pvs = fetch_page_views(client, USER_ID, start, end)
    print(f"Found {len(pvs)} page views.")

    print("Inferring sessions…")
    sessions = infer_sessions(pvs, SESSION_GAP_MINUTES)
    print(f"Inferred {len(sessions)} sessions.")

    print("Fetching submissions (per-course)…")
    subs = fetch_all_submissions(client, USER_ID, start, end)
    print(f"Found {len(subs)} submissions in window.")

    # Write results
    with open("page_views.csv", "w", newline="", encoding="utf-8") as f:
        headers = ["created_at", "asset_type", "asset_id", "context_type", "context_id",
                   "user_request", "url", "interaction_seconds", "remote_ip", "user_agent"]
        write_csv("page_views.csv", pvs, headers)

    with open("sessions.csv", "w", newline="", encoding="utf-8") as f:
        write_csv("sessions.csv", sessions, ["session_start", "session_end", "duration_minutes"])

    with open("submissions.csv", "w", newline="", encoding="utf-8") as f:
        headers = ["course_id","course_name","assignment_id","assignment_name","attempt",
                   "submitted_at","graded_at","score","workflow_state",
                   "late","excused","missing","submission_type","entered_grade","preview_url"]
        write_csv("submissions.csv", subs, headers)

    print("\nDone! Files written:")
    print(" - page_views.csv")
    print(" - sessions.csv")
    print(" - submissions.csv")

if __name__ == "__main__":
    main()
