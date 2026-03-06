import requests
import csv
from urllib.parse import urljoin

#------------------------------------
#The purpose of this script is to determine how many classes in a specific term have assignments
#weighted more than 20% of the final grade.
#------------------------------------

# ==========================
# CONFIGURATION (hard-coded)
# ==========================
BASE_URL = "paste domain here"
TOKEN = "paste token here"

ACCOUNT_ID = 1          # Root or sub-account ID
TERM_ID = 000         # <-- replace with the specific enrollment term ID you want
MIN_WEIGHT = 20.0       # Threshold in % (for groups or single assignments)
OUTPUT_CSV = "weighted_20_with_assignments.csv"
# ==========================


def canvas_get(url, params=None):
    """GET with Canvas pagination + token auth. Returns list of all items."""
    headers = {"Authorization": f"Bearer {TOKEN}"}
    results = []

    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} {resp.text}")
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)

        # pagination via Link header
        next_url = None
        link_header = resp.headers.get("Link", "")
        if link_header:
            for part in link_header.split(","):
                segs = part.split(";")
                if len(segs) < 2:
                    continue
                link_url = segs[0].strip().lstrip("<").rstrip(">")
                rel = segs[1].strip()
                if rel == 'rel="next"':
                    next_url = link_url
                    break

        url = next_url
        # after first request, Canvas pagination URLs are fully formed, so drop params
        params = None

    return results


def list_courses_in_term(account_id, term_id):
    """
    Return only courses in this term.
    workflow_state can be 'available', 'published', 'completed', etc.
    """
    params = {
        "per_page": 100,
        "enrollment_term_id": term_id,
        "include[]": ["term", "total_students", "teachers"],
    }
    url = urljoin(BASE_URL, f"/api/v1/accounts/{account_id}/courses")
    return canvas_get(url, params=params)


def get_assignment_groups(course_id):
    """
    Return assignment groups with weights.
    We'll also ask Canvas to include the assignments in each group in one shot.
    This saves us from doing a second /assignments call per course.
    """
    params = {
        "per_page": 100,
        "include[]": ["assignment_group_weight", "assignments"]
    }
    url = urljoin(BASE_URL, f"/api/v1/courses/{course_id}/assignment_groups")
    return canvas_get(url, params=params)


def analyze_course(course, min_weight):
    """
    Given a single course object, pull its assignment groups (with assignments),
    and figure out:
      1. Any group where group_weight >= min_weight
      2. Any assignment where that ONE assignment is worth >= min_weight of the final grade

    Returns a list of dict rows to write to CSV.
    """
    course_id = course.get("id")
    course_name = course.get("name", "(no name)")
    state = course.get("workflow_state", "")

    try:
        groups = get_assignment_groups(course_id)
    except RuntimeError as e:
        # e.g. permission edge case
        return [{
            "type": "error",
            "course_id": course_id,
            "course_name": course_name,
            "group_or_assignment_id": "",
            "group_or_assignment_name": "",
            "weight_percent": "",
            "details": f"Could not fetch assignment groups: {e}",
            "workflow_state": state,
        }]

    rows = []

    for g in groups:
        group_id = g.get("id")
        group_name = g.get("name", "(no name)")
        # group_weight is the % of the final grade this whole group is worth
        group_weight_raw = g.get("group_weight", 0.0)

        try:
            group_weight = float(group_weight_raw)
        except (TypeError, ValueError):
            group_weight = 0.0

        # --- 1. Check the group itself
        if group_weight >= min_weight:
            rows.append({
                "type": "group",
                "course_id": course_id,
                "course_name": course_name,
                "group_or_assignment_id": group_id,
                "group_or_assignment_name": group_name,
                "weight_percent": round(group_weight, 2),
                "details": "Assignment group weight ≥ threshold",
                "workflow_state": state,
            })

        # --- 2. Check individual assignments inside the group
        assignments = g.get("assignments", []) or []

        # Calculate total points in this group (only count assignments with numeric points_possible)
        group_points_total = 0.0
        for a in assignments:
            pts = a.get("points_possible")
            try:
                pts_val = float(pts) if pts is not None else 0.0
            except (TypeError, ValueError):
                pts_val = 0.0
            group_points_total += pts_val

        # If total is 0, can't divide -> skip per-assignment math
        if group_points_total <= 0 or group_weight <= 0:
            continue

        for a in assignments:
            a_id = a.get("id")
            a_name = a.get("name", "(no name)")
            pts = a.get("points_possible")

            try:
                pts_val = float(pts) if pts is not None else 0.0
            except (TypeError, ValueError):
                pts_val = 0.0

            if pts_val <= 0:
                continue

            # % of final grade this ONE assignment represents
            # = (points_possible / total_points_in_group) * group_weight
            assignment_pct = (pts_val / group_points_total) * group_weight

            if assignment_pct >= min_weight:
                rows.append({
                    "type": "assignment",
                    "course_id": course_id,
                    "course_name": course_name,
                    "group_or_assignment_id": a_id,
                    "group_or_assignment_name": a_name,
                    "weight_percent": round(assignment_pct, 2),
                    "details": (
                        f"Single assignment in '{group_name}' "
                        f"≈ {round(assignment_pct,2)}% of final grade "
                        f"(group {round(group_weight,2)}% total)"
                    ),
                    "workflow_state": state,
                })

    return rows


def build_report():
    # pull courses for the target term
    print(f"📅 Fetching courses for term ID {TERM_ID} ...")
    courses = list_courses_in_term(ACCOUNT_ID, TERM_ID)
    print(f"Found {len(courses)} courses in term {TERM_ID}.")

    all_rows = []
    processed = 0

    for c in courses:
        processed += 1
        cid = c.get("id")
        cname = c.get("name", "(no name)")
        print(f"  [{processed}/{len(courses)}] Analyzing {cid} - {cname} ...")

        # skip obviously deleted shells
        if c.get("workflow_state") == "deleted":
            continue

        course_rows = analyze_course(c, MIN_WEIGHT)
        all_rows.extend(course_rows)

    return all_rows


def write_csv(rows, out_path):
    fields = [
        "type",                         # "group", "assignment", or "error"
        "course_id",
        "course_name",
        "group_or_assignment_id",
        "group_or_assignment_name",
        "weight_percent",
        "details",
        "workflow_state",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    print(f"🔎 Generating report for term {TERM_ID} ...")
    print(f"Threshold: {MIN_WEIGHT}% of total course grade\n")
    rows = build_report()
    print(f"\n✅ Collected {len(rows)} rows meeting or related to threshold.")
    write_csv(rows, OUTPUT_CSV)
    print(f"📄 Report saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

