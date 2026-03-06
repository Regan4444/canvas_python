import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ------------------------------------------------
# CONFIG
# ------------------------------------------------
API_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
BASE_URL = "https://grayson.instructure.com"

COURSE_ID = 44274
STUDENT_SIS_ID = "10112753097"  # optional but recommended

HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


# ------------------------------------------------
# HELPER: UTC → CENTRAL TIME (CST/CDT auto)
# ------------------------------------------------
def utc_to_central(utc_timestamp):
    if not utc_timestamp:
        return None
    utc_time = datetime.fromisoformat(utc_timestamp.replace("Z", "+00:00"))
    central = utc_time.astimezone(ZoneInfo("America/Chicago"))
    return central.strftime("%Y-%m-%d %I:%M:%S %p %Z")


# ------------------------------------------------
# CANVAS PAGINATION
# ------------------------------------------------
def paginate(url, params=None):
    while url:
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code != 200:
            snippet = (r.text or "")[:500].replace("\n", " ")
            raise RuntimeError(f"HTTP {r.status_code} {r.reason}\nURL: {r.url}\nBody: {snippet}")
        yield r.json()
        url = r.links.get("next", {}).get("url")
        params = None


# ------------------------------------------------
# RESOLVE SIS USER → CANVAS USER
# ------------------------------------------------
def get_user_by_sis(sis_id):
    url = f"{BASE_URL}/api/v1/users/sis_user_id:{sis_id}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        snippet = (r.text or "")[:500].replace("\n", " ")
        raise RuntimeError(f"User lookup failed: HTTP {r.status_code}\nURL: {r.url}\nBody: {snippet}")
    user = r.json()
    return user["id"], user.get("name", "(no name)")


# ------------------------------------------------
# LIST ALL ENROLLMENTS IN COURSE, FILTER TO STUDENT
# ------------------------------------------------
def get_student_enrollments_from_course(course_id, target_user_id):
    url = f"{BASE_URL}/api/v1/courses/{course_id}/enrollments"
    params = {
        "per_page": 100,
        "type[]": "StudentEnrollment",
        # include anything that might represent removal/conclusion
        "state[]": ["active", "invited", "completed", "inactive", "deleted"],
        # include some useful extras when Canvas provides them
        "include[]": ["user", "section", "enrollment_term"]
    }

    matches = []
    for page in paginate(url, params):
        for e in page:
            if e.get("user_id") == target_user_id:
                matches.append(e)

    return matches


def summarize(enrollments):
    rows = []
    for e in enrollments:
        rows.append({
            "enrollment_id": e.get("id"),
            "state": (e.get("enrollment_state") or "").lower(),
            "created_at": e.get("created_at"),
            "updated_at": e.get("updated_at"),
            "section_id": e.get("course_section_id"),
            "sis_import_id": e.get("sis_import_id"),
            "role": e.get("role"),
        })
    rows.sort(key=lambda x: (x["updated_at"] or ""))
    return rows


def main():
    user_id, name = get_user_by_sis(STUDENT_SIS_ID)

    print(f"Student:   {name}")
    print(f"Canvas ID:  {user_id}")
    print(f"Course ID:  {COURSE_ID}")

    enrollments = get_student_enrollments_from_course(COURSE_ID, user_id)

    if not enrollments:
        print("\nNo enrollments found for this student in this course (including deleted/inactive).")
        print("If you *know* they were enrolled, possible causes:")
        print("  • They were enrolled in a *different* course shell (cross-list / blueprint / different ID).")
        print("  • They were never enrolled as StudentEnrollment (e.g., Observer/TA role).")
        return

    rows = summarize(enrollments)

    print(f"\nFound {len(rows)} matching enrollment record(s):\n")
    for r in rows:
        print("------------------------------------------------")
        print("Enrollment ID:", r["enrollment_id"])
        print("State:", r["state"])
        print("Created:", utc_to_central(r["created_at"]))
        print("Updated:", utc_to_central(r["updated_at"]))
        print("Section ID:", r["section_id"])
        print("SIS Import ID:", r["sis_import_id"])
        print("Role:", r["role"])

    removed_states = {"deleted", "inactive"}
    removed = [r for r in rows if r["state"] in removed_states and r["updated_at"]]

    if removed:
        best = max(removed, key=lambda x: x["updated_at"])
        print("\n===================================")
        print("BEST AVAILABLE 'REMOVED' TIME:")
        print(utc_to_central(best["updated_at"]))
        print(f"(state='{best['state']}', enrollment_id={best['enrollment_id']})")
        print("===================================")
    else:
        print("\nNo deleted/inactive state found for this student in this course.")
        print("If they disappeared, Canvas may have concluded them (state 'completed') or they are still active.")


if __name__ == "__main__":
    main()