import os
import csv
import requests

# --------- CONFIGURATION ---------
BASE_URL = "paste domain here"   # ex: https://grayson.instructure.com
API_TOKEN = "paste token here"                 # <---- Hard-code your token here

ROOT_ACCOUNT_ID = 0                                # Canvas root account ID (usually 1)
ENROLLMENT_TERM_ID = 000                          # or set to a term ID (ex: 202510)
DEFAULT_SCHEME_ID = 0                              # change this if your Canvas default scheme has another ID

OUTPUT_CSV = "courses_using_canvas_default_scheme.csv"
# ---------------------------------


if not API_TOKEN:
    raise SystemExit("ERROR: API_TOKEN is empty. Please paste your Canvas API token in the script.")


HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


def paginate(url, params=None):
    """
    Canvas pagination helper — yields all items from a multi-page API endpoint.
    """
    while url:
        print(f"Requesting: {url}")
        resp = requests.get(url, headers=HEADERS, params=params)

        try:
            resp.raise_for_status()
        except Exception as e:
            print("\n--- API ERROR ---")
            print("URL:", url)
            print("Error:", e)
            print("Response body:", resp.text[:500])
            print("-----------------\n")
            raise

        data = resp.json()

        if isinstance(data, dict):
            data = [data]

        for item in data:
            yield item

        params = None
        url = resp.links.get("next", {}).get("url")


def get_all_courses(account_id, term_id=None):
    """
    Retrieve all courses in a Canvas account (optionally filter by term).
    """
    url = f"{BASE_URL}/api/v1/accounts/{account_id}/courses"

    params = {
        "per_page": 100,
        "include[]": ["term"],
        "state[]": ["available", "completed", "unpublished"],
    }

    if term_id:
        params["enrollment_term_id"] = term_id

    return paginate(url, params=params)


def get_course_settings(course_id):
    """
    Retrieve settings for a Canvas course.
    """
    url = f"{BASE_URL}/api/v1/courses/{course_id}/settings"
    resp = requests.get(url, headers=HEADERS)

    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Error fetching settings for course {course_id}: {e}")
        print("Response body:", resp.text[:500])
        raise

    return resp.json()


def main():
    # Show exactly where the CSV will be created
    print("Working directory:", os.getcwd())
    print("CSV will be written to:", os.path.abspath(OUTPUT_CSV), "\n")

    rows = []
    total_courses = 0
    total_enabled = 0

    print("Fetching courses...\n")

    for course in get_all_courses(ROOT_ACCOUNT_ID, ENROLLMENT_TERM_ID):
        total_courses += 1
        course_id = course["id"]

        # Pull course settings
        try:
            settings = get_course_settings(course_id)
        except:
            continue

        enabled = settings.get("grading_standard_enabled", False)
        gs_id = settings.get("grading_standard_id")

        try:
            gs_id_int = int(gs_id) if gs_id is not None else None
        except ValueError:
            gs_id_int = None

        if enabled:
            total_enabled += 1

        # Log first 10 courses for verification
        if total_courses <= 10:
            print(f"[DEBUG] Course {course_id}: enabled={enabled}, grading_standard_id={gs_id_int}")

        # Match default grade scheme
        if enabled and gs_id_int == DEFAULT_SCHEME_ID:
            rows.append({
                "course_id": course.get("id"),
                "sis_course_id": course.get("sis_course_id"),
                "course_code": course.get("course_code"),
                "name": course.get("name"),
                "term": course.get("term", {}).get("name"),
                "grading_standard_id": gs_id_int,
            })

    # Write CSV (always writes, even if empty)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "course_id", "sis_course_id", "course_code", "name", "term", "grading_standard_id"
        ])
        writer.writeheader()
        writer.writerows(rows)

    print("\n-------------------------------------------------")
    print(f"Total courses inspected: {total_courses}")
    print(f"Courses with grading_standard_enabled=True: {total_enabled}")
    print(f"Courses USING DEFAULT_SCHEME_ID={DEFAULT_SCHEME_ID}: {len(rows)}")
    print("CSV written to:", os.path.abspath(OUTPUT_CSV))
    print("-------------------------------------------------\n")


if __name__ == "__main__":
    main()

