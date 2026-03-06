#!/usr/bin/env python3
# Canvas: list all courses a student has taken (hard-coded; robust to missing course objects)

import csv, sys, time, requests

# ========= CONFIG (EDIT THESE) =========
CANVAS_DOMAIN = "https://grayson.instructure.com"
ACCESS_TOKEN  = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
STUDENT_REF   = "37704"  # numeric ID, "sis:ID", or "login:user"

# ========= HTTP helpers =========
def sess():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {ACCESS_TOKEN}"})
    return s

def parse_link_header(v):
    if not v: return {}
    out = {}
    for part in v.split(","):
        sec = part.strip().split(";")
        if len(sec) < 2: continue
        url = sec[0].strip()[1:-1]
        rel = None
        for s2 in sec[1:]:
            if "rel=" in s2:
                rel = s2.split("=")[1].strip('"')
        if rel: out[rel] = url
    return out

def robust_get(s, url, params=None, max_retries=4, backoff=0.9):
    attempt = 0
    while True:
        r = s.get(url, params=params, timeout=60)
        if r.status_code in (500,502,503,504,429):
            attempt += 1
            if attempt > max_retries: r.raise_for_status()
            ra = r.headers.get("Retry-After")
            sleep_s = int(ra) if ra and ra.isdigit() else round((backoff**attempt) + 0.25*attempt, 2)
            time.sleep(sleep_s); params=None; continue
        if r.status_code in (401,403,404): r.raise_for_status()
        r.raise_for_status()
        return r

def pages(s, url, params=None):
    next_url, first = url, True
    while next_url:
        r = robust_get(s, next_url, params=params if first else None)
        first = False
        data = r.json()
        if isinstance(data, list):
            for item in data: yield item
        next_url = parse_link_header(r.headers.get("Link")).get("next")

# ========= Canvas helpers =========
def user_path_from_ref(ref: str) -> str:
    if ref.startswith("sis:"):   return f"sis_user_id:{ref.split(':',1)[1]}"
    if ref.startswith("login:"): return f"login_id:{ref.split(':',1)[1]}"
    if ref.isdigit():            return ref
    return f"login_id:{ref}"

def verify_token_and_resolve_user(s, ref: str) -> str:
    me = robust_get(s, f"{CANVAS_DOMAIN}/api/v1/users/self").json()
    print(f"🔐 Token OK. Acting as: {me.get('name')} (id {me.get('id')})")
    cands = [user_path_from_ref(ref)]
    if not ref.startswith(("sis:","login:")):
        if ref.isdigit(): cands += [f"sis_user_id:{ref}", f"login_id:{ref}"]
        else:             cands += [f"sis_user_id:{ref}", f"login_id:{ref}"]
    last = None
    for cand in cands:
        try:
            prof = robust_get(s, f"{CANVAS_DOMAIN}/api/v1/users/{cand}/profile").json()
            print(f"🆔 Resolved user: users/{cand} → {prof.get('name')} (id {prof.get('id')})")
            return cand
        except requests.HTTPError as e:
            last = e
    raise SystemExit(f"❌ Could not resolve user. Last error: {last}")

def strat_A(s, upath):
    # Student enrollments; include course object if available
    url = f"{CANVAS_DOMAIN}/api/v1/users/{upath}/enrollments"
    params = {"type[]":"StudentEnrollment", "include[]":"course", "per_page":100}
    items = list(pages(s, url, params))
    with_course = sum(1 for x in items if x.get("course"))
    with_cid    = sum(1 for x in items if x.get("course_id"))
    print(f"🔎 A: enrollments (student, include=course) → rows={len(items)}, with course={with_course}, with course_id={with_cid}")
    return items

def strat_B(s, upath):
    # Any enrollments; include course, filter locally
    url = f"{CANVAS_DOMAIN}/api/v1/users/{upath}/enrollments"
    params = {"include[]":"course", "per_page":100}
    items = [e for e in pages(s, url, params) if e.get("type")=="StudentEnrollment"]
    with_course = sum(1 for x in items if x.get("course"))
    with_cid    = sum(1 for x in items if x.get("course_id"))
    print(f"🔎 B: enrollments (all, include=course) → rows={len(items)}, with course={with_course}, with course_id={with_cid}")
    return items

def strat_C(s, upath):
    # Courses view; no includes to avoid 500
    url = f"{CANVAS_DOMAIN}/api/v1/users/{upath}/courses"
    params = {"enrollment_type[]":"student", "per_page":100}
    courses = list(pages(s, url, params))
    print(f"🔎 C: courses (enrollment_type=student) → rows={len(courses)}")
    # synthesize into enrollment-like records
    return [{"type":"StudentEnrollment","course":c,"course_id":c.get("id")} for c in courses]

def flatten(enr):
    """Flatten an enrollment into a row with a reliable integer course_id."""
    course = enr.get("course") or {}
    # Prefer embedded course.id; fall back to enrollment.course_id
    cid = course.get("id", None)
    if cid is None:
        cid = enr.get("course_id", None)

    # Force integer when possible (exact-id comparisons later)
    cid_int = None
    if cid is not None:
        try:
            cid_int = int(cid)
        except Exception:
            # leave as None if not parseable; we’ll skip it in dedupe
            pass

    term = course.get("term") or {}
    grades = enr.get("grades") or {}

    return {
        "course_id": cid_int,  # strict int or None
        "course_code": course.get("course_code"),
        "course_name": course.get("name"),
        "term_name": term.get("name"),
        "enrollment_state": enr.get("enrollment_state"),
        "current_score": grades.get("current_score") if isinstance(grades, dict) else None,
        "current_grade": grades.get("current_grade") if isinstance(grades, dict) else None,
        "sis_course_id": course.get("sis_course_id"),
    }

def dedupe_by_course(rows):
    """
    Exact-ID dedupe: only considers rows with a valid integer course_id.
    No substring checks, no string coercion.
    """
    seen = set()
    out = []
    for r in rows:
        cid = r.get("course_id")
        if isinstance(cid, int):
            if cid not in seen:
                seen.add(cid)
                out.append(r)
        # If course_id is missing or not an int, skip it (can’t safely dedupe)
    return out


def write_csv(rows, path="student_courses.csv"):
    headers = ["course_id","course_code","course_name","term_name",
               "enrollment_state","course_workflow_state","start_at","end_at",
               "current_score","current_grade","sis_course_id"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows: w.writerow(r)

# ========= main =========
def main():
    s = sess()
    upath = verify_token_and_resolve_user(s, STUDENT_REF)

    rows = []
    for strat in (strat_A, strat_B, strat_C):
        try:
            items = strat(s, upath)
        except requests.HTTPError as e:
            print(f"   ⚠️ {strat.__name__} error: {e}")
            continue
        if items:
            rows = [flatten(i) for i in items]
            break

    rows = dedupe_by_course(rows)
    print(f"✅ Unique courses: {len(rows)}")
    for r in rows[:25]:
        print(f"{r['term_name'] or '(No Term)'} | {r['course_code'] or ''} | {r['course_name'] or ''}")

    write_csv(rows, "student_courses.csv")
    print("💾 Wrote student_courses.csv")

if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as e:
        sys.exit(f"HTTP error: {e}")
    except requests.RequestException as e:
        sys.exit(f"Network error: {e}")
