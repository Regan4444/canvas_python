
import csv
import requests
from datetime import datetime, timedelta, timezone

# ==============================
# CONFIG
# ==============================
DOMAIN = "paste domain here"
TOKEN = "paste token here"
ROOT_ACCOUNT_ID = 1

DAYS_BACK = 365
CUTOFF_UTC = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)

OUTPUT_FILE = f"deleted_courses_approx_last_{DAYS_BACK}_days_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


# ==============================
# HELPERS
# ==============================
def parse_canvas_dt(dt_str: str):
    """
    Canvas returns ISO8601 like: 2026-02-15T20:11:22Z
    or with offset. Returns aware datetime in UTC.
    """
    if not dt_str:
        return None
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except Exception:
        return None


def get_paged(url, params=None):
    """
    Generator to yield items across Canvas pagination.
    """
    while url:
        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            # Some endpoints return dict-wrapped collections, but these Canvas endpoints usually return lists.
            # If that changes, this will just yield nothing.
            items = []
        else:
            items = data

        for item in items:
            yield item

        url = r.links.get("next", {}).get("url")
        params = None  # next URL already has query params


def list_all_subaccounts(root_account_id: int):
    """
    Returns a list of account IDs including root and all descendants.
    """
    account_ids = [root_account_id]

    # Canvas has /accounts/:id/sub_accounts which is paginated
    url = f"{DOMAIN}/api/v1/accounts/{root_account_id}/sub_accounts"
    params = {"recursive": True, "per_page": 100}

    for acct in get_paged(url, params=params):
        acct_id = acct.get("id")
        if acct_id is not None:
            account_ids.append(acct_id)

    # de-dupe while keeping order
    seen = set()
    out = []
    for a in account_ids:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def list_deleted_courses_for_account(account_id: int):
    """
    Returns summary course objects in deleted state for a given account.
    """
    url = f"{DOMAIN}/api/v1/accounts/{account_id}/courses"
    params = {
        "state[]": ["deleted"],
        "per_page": 100,
        # include some basics if available
        "include[]": ["term", "total_students", "teachers"],
    }

    for course in get_paged(url, params=params):
        yield course


def get_course_detail(course_id: int):
    """
    Pulls full course detail; includes created_at/updated_at and more.
    """
    url = f"{DOMAIN}/api/v1/courses/{course_id}"
    params = {
        "include[]": ["term", "total_students", "teachers", "course_image"]
    }
    r = requests.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def main():
    print(f"Finding courses currently in DELETED state, then filtering to updated in last {DAYS_BACK} days.")
    print(f"Cutoff (UTC): {CUTOFF_UTC.isoformat()}\n")

    account_ids = list_all_subaccounts(ROOT_ACCOUNT_ID)
    print(f"Subaccounts scanned (including root): {len(account_ids)}")

    rows = []
    deleted_count_total = 0
    details_fetched = 0

    for acct_id in account_ids:
        for c in list_deleted_courses_for_account(acct_id):
            deleted_count_total += 1
            course_id = c.get("id")
            if not course_id:
                continue

            # Pull detail so we have updated_at reliably
            try:
                detail = get_course_detail(course_id)
                details_fetched += 1
            except requests.HTTPError as e:
                # If a deleted course can't be read, still record what we have
                detail = c

            updated_at = parse_canvas_dt(detail.get("updated_at"))
            created_at = parse_canvas_dt(detail.get("created_at"))

            # Approx filter: updated_at within last year
            if updated_at and updated_at < CUTOFF_UTC:
                continue

            term_name = (detail.get("term") or {}).get("name", "")
            teachers = detail.get("teachers") or []
            teacher_names = "; ".join(
                [t.get("display_name") or t.get("name") or "" for t in teachers if isinstance(t, dict)]
            ).strip("; ").strip()

            rows.append({
                "course_id": course_id,
                "course_name": detail.get("name") or c.get("name") or "",
                "course_code": detail.get("course_code") or c.get("course_code") or "",
                "sis_course_id": detail.get("sis_course_id") or c.get("sis_course_id") or "",
                "workflow_state": detail.get("workflow_state") or c.get("workflow_state") or "deleted",
                "account_id": detail.get("account_id") or c.get("account_id") or acct_id,
                "term": term_name,
                "created_at_utc": created_at.isoformat() if created_at else "",
                "updated_at_utc": updated_at.isoformat() if updated_at else "",
                "total_students": detail.get("total_students") if "total_students" in detail else "",
                "teachers": teacher_names,
                "course_url": f"{DOMAIN}/courses/{course_id}",
            })

    # Sort newest first by updated_at
    def sort_key(r):
        dt = parse_canvas_dt(r.get("updated_at_utc"))
        return dt or datetime(1970, 1, 1, tzinfo=timezone.utc)

    rows.sort(key=sort_key, reverse=True)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "course_id",
                "course_name",
                "course_code",
                "sis_course_id",
                "workflow_state",
                "account_id",
                "term",
                "created_at_utc",
                "updated_at_utc",
                "total_students",
                "teachers",
                "course_url",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    print("\n---- Summary ----")
    print(f"Deleted courses found (all time, currently deleted): {deleted_count_total}")
    print(f"Course detail calls made: {details_fetched}")
    print(f"Deleted courses with updated_at within last {DAYS_BACK} days: {len(rows)}")
    print(f"\n✅ Exported: {OUTPUT_FILE}")


if __name__ == "__main__":

    main()
