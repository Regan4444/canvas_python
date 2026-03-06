import os, csv, sys, time, requests
from urllib.parse import urljoin

BASE_URL      = os.getenv("CANVAS_BASE_URL", "paste domain here")
TOKEN         = os.getenv("CANVAS_TOKEN",      "paste token here")
ACCOUNT_ID    = int(os.getenv("CANVAS_ACCOUNT_ID", "1"))
TERM_ID       = os.getenv("CANVAS_TERM_ID",    730)   # e.g. "123"
TIMEOUT       = 30

SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {TOKEN}"})

def fetch_all(url, params=None):
    out = []
    while url:
        r = SESSION.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        out.extend(r.json())
        # Canvas-style pagination via Link header
        next_url = None
        if 'Link' in r.headers:
            parts = r.headers['Link'].split(',')
            for p in parts:
                segs = p.split(';')
                if len(segs) >= 2 and 'rel="next"' in segs[1]:
                    next_url = segs[0].strip()[1:-1]
        url, params = next_url, None
    return out

def list_terms(account_id):
    url = urljoin(BASE_URL, f"/api/v1/accounts/{account_id}/terms")
    data = SESSION.get(url, timeout=TIMEOUT).json()
    return data.get("enrollment_terms", [])

def list_courses_in_term(account_id, term_id):
    url = urljoin(BASE_URL, f"/api/v1/accounts/{account_id}/courses")
    params = {
        "enrollment_term_id": term_id,
        "with_enrollments": "true",
        "state[]": "available",      # available = published/active
        "include[]": ["term", "teachers", "course_progress"],
        "published": "true"          # only published courses
    }
    return fetch_all(url, params)

def get_student_enrollment_states(course_id):
    """Return (has_active, has_concluded_only)."""
    url = urljoin(BASE_URL, f"/api/v1/courses/{course_id}/enrollments")
    # Ask specifically for Student enrollments, and check active vs concluded
    params = [
        ("type[]", "StudentEnrollment"),
        ("state[]", "active"),
        ("state[]", "invited"),
        ("state[]", "creation_pending"),
        ("state[]", "completed"),   # concluded in many orgs
        ("per_page", "100")
    ]
    enrollments = fetch_all(url, params=dict(params))
    has_active_like = any(e.get("enrollment_state") in {"active", "invited", "creation_pending"} for e in enrollments)
    has_any_students = any(e.get("type") == "StudentEnrollment" for e in enrollments)
    has_only_concluded = has_any_students and not has_active_like
    return has_active_like, has_only_concluded

def get_course_details(course_id):
    url = urljoin(BASE_URL, f"/api/v1/courses/{course_id}")
    params = {"include[]": ["term", "sections"]}
    r = SESSION.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def main():
    if TERM_ID is None:
        print("TERM_ID not set. Listing terms so you can choose one:\n", file=sys.stderr)
        for t in list_terms(ACCOUNT_ID):
            print(f"Term: {t.get('name')} | id={t.get('id')} | start={t.get('start_at')} | end={t.get('end_at')}")
        print("\nSet CANVAS_TERM_ID to the id you want and re-run.", file=sys.stderr)
        sys.exit(1)

    courses = list_courses_in_term(ACCOUNT_ID, TERM_ID)
    print(f"Found {len(courses)} published courses in term {TERM_ID}. Checking enrollments…", file=sys.stderr)

    rows = []
    for c in courses:
        cid   = c["id"]
        name  = c.get("name")
        code  = c.get("course_code")
        sis   = c.get("sis_course_id")
        term  = (c.get("term") or {}).get("name")
        published = bool(c.get("workflow_state") == "available" or c.get("published"))

        # more precise details
        details = get_course_details(cid)
        end_at  = details.get("end_at")
        start_at = details.get("start_at")
        restrict = details.get("restrict_enrollments_to_course_dates")  # bool or None

        has_active, has_only_concluded = get_student_enrollment_states(cid)

        rows.append({
            "course_id": cid,
            "sis_course_id": sis,
            "course_code": code,
            "name": name,
            "term": term,
            "published": published,
            "start_at": start_at,
            "end_at": end_at,
            "restrict_to_course_dates": restrict,
            "has_active_student_enrollments": has_active,
            "has_only_concluded_student_enrollments": has_only_concluded
        })
        # be polite to API rate limits
        time.sleep(0.1)

    # Write a CSV
    outpath = "last_semester_visibility_report.csv"
    with open(outpath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to {outpath}")
    print("Interpretation tips:")
    print("- has_active_student_enrollments=True → likely still on students’ Dashboards & fully visible.")
    print("- has_only_concluded_student_enrollments=True → typically visible under Past Enrollments (read-only),")
    print("  unless your account setting ‘Restrict students from viewing courses after term/course end date’ is enabled.")

if __name__ == "__main__":

    main()
