#!/usr/bin/env python3
"""
Canvas Respondus LockDown Browser (LDB) Audit
- Audits courses in a term
- Uses a semester date window to count exams in timeframe
- Adds direct course links
- Adds a "no published content" flag (heuristic)
- Outputs CSV

Notes:
- Does NOT launch Respondus or verify tool-side settings.
- "New Quizzes" detection is heuristic via Assignments external tool patterns.
- "No published content" is heuristic (published assignments/pages/modules/quizzes).
"""

import csv
import argparse
import datetime as dt
import requests
from urllib.parse import urljoin

# =====================================================
# HARD-CODED CONFIG
# =====================================================

CANVAS_BASE_URL = "paste domain here"

# >>>>>>>>> PUT YOUR TOKEN HERE <<<<<<<<<
CANVAS_TOKEN = "4480~PUT_YOUR_REAL_TOKEN_HERE"

ACCOUNT_ID = 1   # Root account usually = 1


# =====================================================
# Helpers
# =====================================================

def headers():
    return {"Authorization": f"Bearer {CANVAS_TOKEN}"}


def iso_to_dt(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def in_window(d, start, end):
    return d and start <= d <= end


def get_paginated(session, url, params=None):
    """Yield list items across Canvas pagination."""
    params = params or {}
    while url:
        r = session.get(url, params=params)
        r.raise_for_status()
        data = r.json()

        # Most Canvas list endpoints return a list
        if isinstance(data, dict):
            yield data
            return

        for item in data:
            yield item

        link = r.headers.get("Link", "")
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip()[1:-1]
                break
        url = next_url
        params = {}


def course_link(course_id: int) -> str:
    return f"{CANVAS_BASE_URL}/courses/{course_id}"


# =====================================================
# LDB NAV CHECK
# =====================================================

def check_ldb_tab(session, api, course_id):
    """
    Checks /courses/:id/tabs for a tab label containing lockdown/respondus.
    """
    url = f"{api}/courses/{course_id}/tabs"
    try:
        tabs = list(get_paginated(session, url))
    except Exception:
        return False, "", ""

    for t in tabs:
        label = (t.get("label") or t.get("name") or "").lower()
        if "lockdown" in label or "respondus" in label:
            return True, str(bool(t.get("hidden"))), t.get("id")

    return False, "", ""


def find_ldb_external_tool_link(session, api, course_id):
    """
    Best-effort attempt to find the course-level external tool entry for Respondus.
    If found, returns a direct link: /courses/:id/external_tools/:tool_id

    NOTE: Depending on how Respondus is configured, this may not return anything.
    """
    url = f"{api}/courses/{course_id}/external_tools"
    params = {"per_page": 100}

    try:
        tools = list(get_paginated(session, url, params))
    except Exception:
        return ""

    # Look for common naming patterns
    for tool in tools:
        name = (tool.get("name") or "").lower()
        if "lockdown" in name or "respondus" in name:
            tool_id = tool.get("id")
            if tool_id:
                return f"{CANVAS_BASE_URL}/courses/{course_id}/external_tools/{tool_id}"

    return ""


# =====================================================
# CLASSIC QUIZZES
# =====================================================

def audit_classic(session, api, cid, start, end):
    """
    Classic quizzes endpoint: /courses/:id/quizzes
    Counts total/published and "in timeframe" using due/unlock/lock dates.
    """
    url = f"{api}/courses/{cid}/quizzes"

    total = published = timeframe = missing = 0
    error = ""

    try:
        quizzes = list(get_paginated(session, url, {"per_page": 100}))
    except Exception as e:
        return 0, 0, 0, 0, "error"

    for q in quizzes:
        total += 1
        if q.get("published"):
            published += 1

        due = iso_to_dt(q.get("due_at"))
        unlock = iso_to_dt(q.get("unlock_at"))
        lock = iso_to_dt(q.get("lock_at"))

        dates = [d for d in (due, unlock, lock) if d]

        if not dates:
            missing += 1
            continue

        if any(in_window(d, start, end) for d in dates):
            timeframe += 1

    return total, published, timeframe, missing, error


# =====================================================
# NEW QUIZ HEURISTIC
# =====================================================

def looks_like_new_quiz(a):
    """
    Heuristic for New Quizzes: assignment with submission_type external_tool and
    external tool url containing typical new quiz patterns.
    """
    if "external_tool" not in (a.get("submission_types") or []):
        return False

    ext = a.get("external_tool_tag_attributes") or {}
    url = (ext.get("url") or "").lower()

    return any(x in url for x in [
        "quizzes.next",
        "new_quizzes",
        "quizzes_lti",
        "lti/quizzes",
        "/lti/"
    ])


def audit_newquiz(session, api, cid, start, end):
    """
    Uses /courses/:id/assignments and counts "new quiz candidates".
    Timeframe: due_at.
    """
    url = f"{api}/courses/{cid}/assignments"

    total = timeframe = missing = 0
    error = ""

    try:
        for a in get_paginated(
            session,
            url,
            {
                "per_page": 100,
                "include[]": ["submission_types", "external_tool_tag_attributes"]
            }
        ):
            if looks_like_new_quiz(a):
                total += 1
                due = iso_to_dt(a.get("due_at"))
                if not due:
                    missing += 1
                elif in_window(due, start, end):
                    timeframe += 1
    except Exception:
        error = "error"

    return total, timeframe, missing, error


# =====================================================
# PUBLISHED CONTENT COUNTS (for "no published content" flag)
# =====================================================

def count_published_assignments(session, api, cid):
    url = f"{api}/courses/{cid}/assignments"
    count = 0
    try:
        for a in get_paginated(session, url, {"per_page": 100}):
            if a.get("published") is True:
                count += 1
    except Exception:
        return 0, "error"
    return count, ""


def count_published_pages(session, api, cid):
    # Pages endpoint returns objects that usually include "published" when authenticated as teacher/admin.
    url = f"{api}/courses/{cid}/pages"
    count = 0
    try:
        for p in get_paginated(session, url, {"per_page": 100}):
            if p.get("published") is True:
                count += 1
    except Exception:
        return 0, "error"
    return count, ""


def count_published_modules(session, api, cid):
    url = f"{api}/courses/{cid}/modules"
    count = 0
    try:
        for m in get_paginated(session, url, {"per_page": 100}):
            if m.get("published") is True:
                count += 1
    except Exception:
        return 0, "error"
    return count, ""


# =====================================================
# MAIN
# =====================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--term-id", type=int, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--out", default="respondus_ldb_audit.csv")

    args = parser.parse_args()

    start = iso_to_dt(args.start)
    end = iso_to_dt(args.end)
    if not start or not end:
        raise SystemExit("ERROR: Start/end must be ISO datetimes like 2026-01-12T00:00:00-06:00")

    api = urljoin(CANVAS_BASE_URL + "/", "api/v1").rstrip("/")

    session = requests.Session()
    session.headers.update(headers())

    print("Fetching courses...")

    courses = list(get_paginated(
        session,
        f"{api}/accounts/{ACCOUNT_ID}/courses",
        {
            "per_page": 100,
            "enrollment_term_id": args.term_id,
            "include[]": ["course_code", "sis_course_id", "workflow_state", "start_at", "end_at"]
        }
    ))

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        writer.writerow([
            # identity / links
            "course_id", "sis_course_id", "course_code", "course_name",
            "course_link", "ldb_tool_link",

            # publish state
            "course_published",

            # course dates (useful context)
            "course_start_at", "course_end_at",

            # ldb nav
            "ldb_nav_present", "ldb_hidden",

            # classic quiz stats
            "classic_total", "classic_published",
            "classic_in_timeframe", "classic_missing_dates", "classic_error",

            # new quiz candidate stats
            "newquiz_candidates_total", "newquiz_in_timeframe",
            "newquiz_missing_due", "newquiz_error",

            # published content stats
            "published_assignments",
            "published_pages",
            "published_modules",
            "published_classic_quizzes",

            # flags
            "needs_ldb_check",
            "no_published_content",
            "notes"
        ])

        for c in courses:
            cid = c["id"]

            c_name = c.get("name", "")
            c_code = c.get("course_code", "")
            c_sis = c.get("sis_course_id", "")

            course_published = (c.get("workflow_state") == "available")

            c_start = c.get("start_at", "") or ""
            c_end = c.get("end_at", "") or ""

            # Links
            c_link = course_link(cid)

            # LDB nav presence + best-effort external tool direct link
            ldb_present, ldb_hidden, _ = check_ldb_tab(session, api, cid)
            ldb_tool_link = find_ldb_external_tool_link(session, api, cid)

            # Exams audit
            ct, cp, ci, cm, c_err = audit_classic(session, api, cid, start, end)
            nt, ni, nm, n_err = audit_newquiz(session, api, cid, start, end)

            # Published content (heuristic)
            pub_assign, a_err = count_published_assignments(session, api, cid)
            pub_pages, p_err = count_published_pages(session, api, cid)
            pub_modules, m_err = count_published_modules(session, api, cid)

            published_classic_quizzes = cp

            # Flags
            needs_check = (ci + ni) > 0

            no_published_content = (
                published_classic_quizzes == 0
                and pub_assign == 0
                and pub_pages == 0
                and pub_modules == 0
            )

            notes = []
            if needs_check and not ldb_present:
                notes.append("Exams in timeframe but no LDB nav link found")
            if not ldb_tool_link and ldb_present:
                notes.append("LDB nav exists but course external tool link not found (may be configured differently)")
            if c_err:
                notes.append(f"classic_quiz_api:{c_err}")
            if n_err:
                notes.append(f"newquiz_assignments_api:{n_err}")
            if a_err or p_err or m_err:
                notes.append("one_or_more_content_endpoints_errored_or_no_permission")
            if no_published_content:
                notes.append("No published assignments/pages/modules/classic quizzes found")

            writer.writerow([
                cid, c_sis, c_code, c_name,
                c_link, ldb_tool_link,

                course_published,

                c_start, c_end,

                ldb_present, ldb_hidden,

                ct, cp, ci, cm, c_err,

                nt, ni, nm, n_err,

                pub_assign,
                pub_pages,
                pub_modules,
                published_classic_quizzes,

                needs_check,
                no_published_content,
                "; ".join(notes)
            ])

            print(f"Audited course {cid}")

    print(f"\nDONE → {args.out}")
    print(f"Courses scanned: {len(courses)}")


if __name__ == "__main__":
    main()

