import requests
from datetime import datetime, timezone

# ---------------------------
# CONFIG
# ---------------------------
API_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
BASE_URL = "https://grayson.instructure.com"

COURSE_ID = 44413                  # Canvas numeric course id
STUDENT_SIS_ID = "10112767432"     # e.g. "A1234567"

HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


def parse_dt(s):
    if not s:
        return None
    # Canvas timestamps often look like: 2026-01-12T14:22:18Z
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params)
    if r.status_code != 200:
        snippet = (r.text or "")[:500].replace("\n", " ")
        raise RuntimeError(f"HTTP {r.status_code} {r.reason}\nURL: {r.url}\nBody: {snippet}")
    return r


def paginate(url, params):
    while url:
        r = get(url, params=params)
        yield r.json()
        url = r.links.get("next", {}).get("url")
        params = None  # next url already includes params


def resolve_user_id_from_sis(sis_id):
    url = f"{BASE_URL}/api/v1/users/sis_user_id:{sis_id}"
    user = get(url).json()
    return user["id"], user.get("name", "(no name)")


def list_enrollments_via_course_filter(course_id, sis_id):
    """
    Primary approach:
    /courses/:course_id/enrollments with sis_user_id[] filter (works in many environments)
    """
    url = f"{BASE_URL}/api/v1/courses/{course_id}/enrollments"
    params = {
        "per_page": 100,
        "type[]": "StudentEnrollment",
        "sis_user_id[]": sis_id,
        "state[]": ["active", "invited", "completed", "inactive", "deleted"],
    }
    enrollments = []
    for page in paginate(url, params):
        enrollments.extend(page)
    return enrollments


def list_enrollments_via_user_in_course(course_id, user_id):
    """
    Fallback approach:
    /courses/:course_id/users/:user_id/enrollments (very reliable)
    """
    url = f"{BASE_URL}/api/v1/courses/{course_id}/users/{user_id}/enrollments"
    params = {"per_page": 100, "state[]": ["active", "invited", "completed", "inactive", "deleted"]}
    enrollments = []
    for page in paginate(url, params):
        enrollments.extend(page)
    # Filter to StudentEnrollment in case the user also has other roles
    enrollments = [e for e in enrollments if (e.get("type") == "StudentEnrollment" or e.get("role") == "StudentEnrollment")]
    return enrollments


def summarize(enrollments):
    rows = []
    for e in enrollments:
        rows.append({
            "enrollment_id": e.get("id"),
            "state": (e.get("enrollment_state") or "").lower(),
            "created_at_utc": parse_dt(e.get("created_at")),
            "updated_at_utc": parse_dt(e.get("updated_at")),
            "sis_import_id": e.get("sis_import_id"),
            "section_id": e.get("course_section_id"),
            "role": e.get("role"),
        })
    rows.sort(key=lambda x: (x["updated_at_utc"] or datetime.min.replace(tzinfo=timezone.utc)))
    return rows


def main():
    user_id, user_name = resolve_user_id_from_sis(STUDENT_SIS_ID)
    print(f"Found user: {user_name} (Canvas ID: {user_id})")

    # Try course enrollments filter first, fallback to user-in-course enrollments
    try:
        enrollments = list_enrollments_via_course_filter(COURSE_ID, STUDENT_SIS_ID)
    except Exception as ex:
        print("\nCourse enrollment filter method failed; trying user-in-course fallback.")
        print(str(ex))
        enrollments = []

    if not enrollments:
        enrollments = list_enrollments_via_user_in_course(COURSE_ID, user_id)

    if not enrollments:
        print("\nNo enrollment records found for that student in that course (including deleted/inactive).")
        return

    rows = summarize(enrollments)

    print(f"\nFound {len(rows)} enrollment record(s) for this student in course {COURSE_ID}:\n")
    for r in rows:
        print("----")
        print(f"Enrollment ID:    {r['enrollment_id']}")
        print(f"State:            {r['state']}")
        print(f"Created (UTC):    {r['created_at_utc']}")
        print(f"Updated (UTC):    {r['updated_at_utc']}")
        print(f"SIS Import ID:    {r['sis_import_id']}")
        print(f"Section ID:       {r['section_id']}")
        print(f"Role:             {r['role']}")

    removed_states = {"deleted", "inactive"}
    removed = [r for r in rows if r["state"] in removed_states and r["updated_at_utc"]]

    if removed:
        best = max(removed, key=lambda x: x["updated_at_utc"])
        print("\n======================================")
        print("BEST AVAILABLE 'REMOVED' TIME (UTC):")
        print(best["updated_at_utc"])
        print(f"(state='{best['state']}', enrollment_id={best['enrollment_id']})")
        print("======================================")
    else:
        print("\nNo deleted/inactive enrollment record found.")
        print("They may still be active, or concluded (completed), or removed in a way reflected as 'completed' instead of deleted.")


if __name__ == "__main__":
    main()