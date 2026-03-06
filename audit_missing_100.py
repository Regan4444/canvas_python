#!/usr/bin/env python3
"""
Audit: flag courses where Missing Submission Policy effectively awards 100%.

Canvas stores missing policy as "percentage points to deduct" (missing_submission_deduction).
So "Missing = 100%"  ==> enabled AND deduction == 0. :contentReference[oaicite:1]{index=1}

Outputs:
- Console summary
- CSV of flagged courses
"""

import csv
import time
import requests
from typing import Dict, Any, List, Optional


# ====== EDIT THESE ======
BASE_URL = "https://grayson.instructure.com"
TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
ROOT_ACCOUNT_ID = 1

# Set this to the enrollment_term_id for the semester you want to audit
TERM_ID = 729  # <-- CHANGE ME (e.g., 123)
# =======================


def auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def parse_link_header(link_header: str) -> Dict[str, str]:
    links = {}
    if not link_header:
        return links
    for part in link_header.split(","):
        section = [s.strip() for s in part.split(";")]
        if len(section) < 2:
            continue
        url = section[0]
        rel = None
        for s in section[1:]:
            if s.startswith('rel='):
                rel = s.split("=", 1)[1].strip().strip('"')
        if rel and url.startswith("<") and url.endswith(">"):
            links[rel] = url[1:-1]
    return links


def paged_get(url: str, params: Dict[str, Any]) -> List[Any]:
    out: List[Any] = []
    next_url = url
    next_params = params

    while next_url:
        r = requests.get(next_url, headers=auth_headers(), params=next_params, timeout=60)
        r.raise_for_status()
        out.extend(r.json())
        links = parse_link_header(r.headers.get("Link", ""))
        if "next" in links:
            next_url = links["next"]
            next_params = None
        else:
            next_url = None

    return out


def list_courses_in_term(account_id: int, term_id: int) -> List[Dict[str, Any]]:
    # List courses in an account, filter by term
    url = f"{BASE_URL}/api/v1/accounts/{account_id}/courses"
    params = {
        "enrollment_term_id": term_id,
        "per_page": 100,
        # include[] helps you identify courses in reports
        "include[]": ["term", "total_students", "teachers", "course_image"],
    }
    return paged_get(url, params)


def get_late_policy(course_id: int) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL}/api/v1/courses/{course_id}/late_policy"
    r = requests.get(url, headers=auth_headers(), timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    # ✅ Your instance returns {"late_policy": {...}}
    return data.get("late_policy", data)



def is_missing_awards_100(late_policy: Dict[str, Any]) -> bool:
    enabled = bool(late_policy.get("missing_submission_deduction_enabled"))
    deduction = late_policy.get("missing_submission_deduction")
    # Deduction of 0 => 100% awarded for missing submissions :contentReference[oaicite:3]{index=3}
    try:
        deduction_num = float(deduction)
    except (TypeError, ValueError):
        return False
    return enabled and deduction_num == 0.0


def main():
    if TERM_ID in (0, None):
        raise SystemExit("ERROR: Set TERM_ID at top of script to the enrollment_term_id you want to audit.")

    t0 = time.time()
    print(f"Auditing account {ROOT_ACCOUNT_ID} for term {TERM_ID}…")

    courses = list_courses_in_term(ROOT_ACCOUNT_ID, TERM_ID)
    print(f"Found {len(courses)} course(s). Checking late policies…")

    flagged = []
    checked = 0

    for c in courses:
        course_id = c.get("id")
        if not course_id:
            continue

        checked += 1
        try:
            lp = get_late_policy(course_id)
        except requests.HTTPError as e:
            print(f"WARNING: course {course_id} late_policy error: {e}")
            continue

        if lp and is_missing_awards_100(lp):
            flagged.append({
                "course_id": course_id,
                "sis_course_id": c.get("sis_course_id") or "",
                "course_name": c.get("name") or "",
                "course_code": c.get("course_code") or "",
                "workflow_state": c.get("workflow_state") or "",
                "missing_deduction_enabled": lp.get("missing_submission_deduction_enabled"),
                "missing_deduction": lp.get("missing_submission_deduction"),
                "late_policy_updated_at": lp.get("updated_at") or "",
            })

    out_file = f"missing_policy_100_term_{TERM_ID}.csv"
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flagged[0].keys()) if flagged else [
            "course_id","sis_course_id","course_name","course_code","workflow_state",
            "missing_deduction_enabled","missing_deduction","late_policy_updated_at"
        ])
        w.writeheader()
        for row in flagged:
            w.writerow(row)

    dt_s = round(time.time() - t0, 1)
    print(f"\nChecked {checked} course(s) in {dt_s}s.")
    print(f"FLAGGED {len(flagged)} course(s) where Missing effectively awards 100%.")
    print(f"CSV written: {out_file}")


if __name__ == "__main__":
    main()
