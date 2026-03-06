import requests
import datetime
from urllib.parse import urljoin
import pytz

#---------------------------------------------------------
#The purpose of the script is to determine if a student was active in a course on a specific date
#--------------------------------------------------------

# ---------------------------------------------------------
# HARD-CODED CONFIGURATION SECTION
# ---------------------------------------------------------
BASE_URL = "paste domain here"   # Canvas domain
TOKEN = "paste token here"           # Canvas API token
COURSE_ID = 00000                              # Course ID to check
USER_ID = 00000                                # Student user ID
DATE_TO_CHECK = "0000-00-00"                   # Local Central date to verify
# ---------------------------------------------------------

CENTRAL = pytz.timezone("America/Chicago")


def central_day_bounds(date_str):
    """
    Take a local Central date (YYYY-MM-DD) and return:
    - local_start (Central tz aware, 00:00:00)
    - local_end   (Central tz aware, 23:59:59)
    """
    day = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    start_local = CENTRAL.localize(day.replace(hour=0, minute=0, second=0, microsecond=0))
    end_local = CENTRAL.localize(day.replace(hour=23, minute=59, second=59, microsecond=0))
    return start_local, end_local


def buffered_utc_window(local_start, local_end, buffer_hours=2):
    """
    Add +/- buffer_hours around the local window, convert to UTC ISO8601,
    and return (start_iso, end_iso).
    """
    start_buf = local_start - datetime.timedelta(hours=buffer_hours)
    end_buf = local_end + datetime.timedelta(hours=buffer_hours)

    start_utc = start_buf.astimezone(pytz.utc)
    end_utc = end_buf.astimezone(pytz.utc)

    return start_utc.isoformat(), end_utc.isoformat()


def get_page_views(base_url, token, user_id, start_iso, end_iso):
    headers = {"Authorization": f"Bearer {token}"}
    page_views = []
    url = urljoin(base_url, f"/api/v1/users/{user_id}/page_views")
    params = {"start_time": start_iso, "end_time": end_iso, "per_page": 100}

    while url:
        resp = requests.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Error {resp.status_code} getting page views: {resp.text}")
        data = resp.json()
        if isinstance(data, list):
            page_views.extend(data)
        else:
            # safety
            break

        # pagination
        link = resp.headers.get("Link", "")
        next_url = None
        if link:
            for segment in link.split(","):
                parts = segment.split(";")
                if len(parts) < 2:
                    continue
                link_url = parts[0].strip().lstrip("<").rstrip(">")
                rel = parts[1].strip()
                if rel == 'rel="next"':
                    next_url = link_url
                    break
        url = next_url
        params = {}

    return page_views


def parse_canvas_timestamp_to_central(ts_str):
    """
    Canvas gives timestamps like '2025-10-15T14:22:05Z' (UTC).
    Convert to Central and return (aware_dt_local, formatted_string).
    """
    # make it ISO 8601 friendly for fromisoformat
    aware_utc = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    local = aware_utc.astimezone(CENTRAL)
    return local, local.strftime("%Y-%m-%d %H:%M:%S %Z")


def activity_matches_course(pv, course_id_int):
    """
    Decide if this page view is course-related.
    Strategy:
      1. direct match on context_type/context_id
      2. OR URL starts with /courses/{COURSE_ID}
    """
    # 1. direct context match
    if pv.get("context_type") == "Course" and pv.get("context_id") == course_id_int:
        return True

    # 2. URL pattern match
    url_path = pv.get("url") or ""
    needle = f"/courses/{course_id_int}"
    if needle in url_path:
        return True

    return False


def filter_hits_for_day_and_course(page_views, course_id, local_start, local_end):
    """
    - Convert each view timestamp to Central time
    - Keep only views whose local time is between local_start and local_end
    - Keep only views tied to the course (by context or URL pattern)
    Return (hits, debug_info)
    """
    course_id_int = int(course_id)
    hits = []
    debug_sample = []  # up to ~10 raw-ish views for troubleshooting

    for pv in page_views:
        ts_raw = pv.get("created_at")
        if not ts_raw:
            continue

        try:
            ts_local_dt, ts_local_str = parse_canvas_timestamp_to_central(ts_raw)
        except Exception:
            # if timestamp parses weird, skip
            continue

        # check if timestamp falls on that Central calendar day
        if not (local_start <= ts_local_dt <= local_end):
            # even if it's out of range, capture a few for debug
            if len(debug_sample) < 10:
                debug_sample.append({
                    "timestamp_local": ts_local_str,
                    "url": pv.get("url"),
                    "context_type": pv.get("context_type"),
                    "context_id": pv.get("context_id"),
                })
            continue

        # Now see if this looks like course activity
        if activity_matches_course(pv, course_id_int):
            hits.append({
                "timestamp_local": ts_local_str,
                "asset_type": pv.get("asset_type"),
                "url": pv.get("url"),
                "interaction_seconds": pv.get("interaction_seconds"),
                "context_type": pv.get("context_type"),
                "context_id": pv.get("context_id"),
            })
        else:
            # Also include a few "near-miss" items in debug, so you can see what we're skipping
            if len(debug_sample) < 10:
                debug_sample.append({
                    "timestamp_local": ts_local_str,
                    "url": pv.get("url"),
                    "context_type": pv.get("context_type"),
                    "context_id": pv.get("context_id"),
                })

    return hits, debug_sample


def main():
    print(f"🔎 Checking activity for user {USER_ID} in course {COURSE_ID} on {DATE_TO_CHECK} (Central Time)")

    # 1. Build local day bounds
    local_start, local_end = central_day_bounds(DATE_TO_CHECK)

    # 2. Build buffered UTC window for API call
    start_iso, end_iso = buffered_utc_window(local_start, local_end, buffer_hours=2)

    # 3. Fetch page views (raw from Canvas)
    views = get_page_views(BASE_URL, TOKEN, USER_ID, start_iso, end_iso)

    print(f"ℹ️ Canvas returned {len(views)} total page view records in the buffered window.")

    # 4. Filter down to stuff on that local date AND tied to the course
    hits, debug_sample = filter_hits_for_day_and_course(
        views,
        COURSE_ID,
        local_start,
        local_end
    )

    if hits:
        print(f"✅ YES: Student was active in course {COURSE_ID} on {DATE_TO_CHECK}")
        print("Details (Central Time):")
        for h in hits:
            print(f" - {h['timestamp_local']}  {h['asset_type']}  {h['url']}  "
                  f"(interaction_seconds={h['interaction_seconds']}, "
                  f"context={h['context_type']}:{h['context_id']})")
    else:
        print(f"❌ NO direct course-tagged hits for that date.")
        print("🔍 Debug info (closest matches Canvas DID log that day or near day):")
        for d in debug_sample:
            print(f" - {d['timestamp_local']}  {d['url']}  "
                  f"context={d['context_type']}:{d['context_id']}")

        print("\nPossible reasons:")
        print("  • The student used an external tool / file link that Canvas didn’t tag with the course_id.")
        print("  • Your token cannot see their page views for this course.")
        print("  • Activity happened right at the edge of the day before/after, not in this day’s window.")


if __name__ == "__main__":
    main()

