#!/usr/bin/env python3
"""
Find all UNPUBLISHED Canvas courses for a given Enrollment Term (semester).

Examples:
  python find_unpublished_courses.py --base-url https://grayson.instructure.com --account-id 1 --term-id 123
  python find_unpublished_courses.py --base-url https://grayson.instructure.com --account-id 1 --sis-term-id "2026SP"
  python find_unpublished_courses.py --base-url https://grayson.instructure.com --account-id 1 --term-name "Spring 2026" --csv out.csv
"""

import argparse
import csv
import sys
from typing import List, Optional
import requests


# ============================================================
# HARD-CODE YOUR TOKEN HERE:
CANVAS_TOKEN = "4480~yTwt773FmtHx7ZxcQ8AB3nLTG8uZnfAvANWQVfuyacB2DV3mtzrAzWPBzZfKHLVU"
# ============================================================


def api_get_all(session: requests.Session, url: str, params: Optional[dict] = None) -> List[dict]:
    """GET all pages from a Canvas API collection endpoint."""
    items: List[dict] = []
    while url:
        r = session.get(url, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"GET failed {r.status_code}: {r.text}")
        data = r.json()
        if isinstance(data, list):
            items.extend(data)
        else:
            items.append(data)

        # Parse Link header for rel="next"
        next_url = None
        link = r.headers.get("Link", "")
        if link:
            parts = [p.strip() for p in link.split(",")]
            for p in parts:
                if 'rel="next"' in p:
                    next_url = p[p.find("<") + 1 : p.find(">")]
                    break

        url = next_url
        params = None  # next_url already includes query params
    return items


def resolve_term_id(
    session: requests.Session,
    base_url: str,
    account_id: int,
    term_id: Optional[int],
    sis_term_id: Optional[str],
    term_name: Optional[str],
) -> int:
    """Resolve an enrollment term id from term_id, sis_term_id, or term_name (contains match)."""
    if term_id is not None:
        return term_id

    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/terms"
    params = {
        "per_page": 100,
        "workflow_state[]": ["active", "deleted"],
        "include[]": ["overrides"],
    }

    resp = session.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"Term lookup failed {resp.status_code}: {resp.text}")

    payload = resp.json()
    terms = payload.get("enrollment_terms", [])

    if sis_term_id:
        for t in terms:
            if str(t.get("sis_term_id", "")).strip() == sis_term_id.strip():
                return int(t["id"])
        raise RuntimeError(f"Could not find term with sis_term_id={sis_term_id}")

    if term_name:
        needle = term_name.strip().lower()
        matches = [t for t in terms if needle in str(t.get("name", "")).lower()]
        if not matches:
            raise RuntimeError(f'Could not find term with name containing "{term_name}"')
        if len(matches) > 1:
            matches.sort(key=lambda t: len(str(t.get("name", ""))))
        return int(matches[0]["id"])

    raise RuntimeError("You must supply one of: --term-id, --sis-term-id, or --term-name")


def main() -> int:
    ap = argparse.ArgumentParser(description="Find all unpublished Canvas courses for a given enrollment term.")
    ap.add_argument("--base-url", required=True, help="Canvas base URL, e.g. https://school.instructure.com")
    ap.add_argument("--account-id", type=int, required=True, help="Account or subaccount ID to search in")

    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--term-id", type=int, help="Enrollment term ID")
    g.add_argument("--sis-term-id", help="SIS term ID (e.g. 2026SP)")
    g.add_argument("--term-name", help='Term name contains match (e.g. "Spring 2026")')

    ap.add_argument("--csv", help="Optional output CSV path")
    args = ap.parse_args()

    if not CANVAS_TOKEN or CANVAS_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        print("ERROR: You must hard-code your Canvas token in CANVAS_TOKEN.", file=sys.stderr)
        return 1

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {CANVAS_TOKEN}"})

    term_id = resolve_term_id(
        session=session,
        base_url=args.base_url,
        account_id=args.account_id,
        term_id=args.term_id,
        sis_term_id=args.sis_term_id,
        term_name=args.term_name,
    )

    courses_url = f"{args.base_url.rstrip('/')}/api/v1/accounts/{args.account_id}/courses"

    # Try to have Canvas filter to unpublished as much as possible
    params = {
        "per_page": 100,
        "enrollment_term_id": term_id,
        "include[]": ["term", "total_students"],
        "published": "false",
    }

    all_courses = api_get_all(session, courses_url, params=params)

    # Safety filter (some accounts return extra results)
    unpublished = []
    for c in all_courses:
        wf = str(c.get("workflow_state", "")).lower()
        pub = c.get("published", None)
        if wf == "unpublished" or pub is False:
            unpublished.append(c)

    unpublished.sort(key=lambda x: (str(x.get("sis_course_id", "")), str(x.get("name", ""))))

    print(f"Account ID: {args.account_id}")
    print(f"Enrollment Term ID: {term_id}")
    print(f"Unpublished courses found: {len(unpublished)}")
    print("-" * 80)

    for c in unpublished:
        print(
            f'{c.get("id")} | {c.get("course_code","")} | {c.get("name","")} '
            f'| sis_course_id={c.get("sis_course_id","")} | state={c.get("workflow_state","")} '
            f'| published={c.get("published","")}'
        )

    if args.csv:
        fieldnames = [
            "id",
            "name",
            "course_code",
            "sis_course_id",
            "workflow_state",
            "published",
            "term_id",
            "term_name",
            "total_students",
        ]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for c in unpublished:
                term = c.get("term") or {}
                w.writerow(
                    {
                        "id": c.get("id"),
                        "name": c.get("name"),
                        "course_code": c.get("course_code"),
                        "sis_course_id": c.get("sis_course_id"),
                        "workflow_state": c.get("workflow_state"),
                        "published": c.get("published"),
                        "term_id": term.get("id"),
                        "term_name": term.get("name"),
                        "total_students": c.get("total_students"),
                    }
                )

        print("-" * 80)
        print(f"Wrote CSV: {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
