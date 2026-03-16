"""
browser_history.py — Reads Chrome's local browsing history for a given date.

Chrome stores history in a SQLite file at:
  %LOCALAPPDATA%/Google/Chrome/User Data/Default/History

Problem: Chrome locks this file while it's running, so we can't open it directly.
Solution: We copy it to a temp file first, then read from the copy.

Chrome stores timestamps as microseconds since January 1, 1601 (Windows FILETIME).
We convert these to normal Python datetime objects.
"""

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta

CHROME_HISTORY_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Google", "Chrome", "User Data", "Default", "History"
)

# URL fragments that indicate a meeting (Teams, Zoom, Google Meet, Webex, Whereby)
MEETING_PATTERNS = [
    "teams.microsoft.com/l/meetup-join",
    "teams.live.com/meet",
    "zoom.us/j/",
    "meet.google.com/",
    "webex.com/meet",
    "whereby.com/",
]

# Seconds between Windows epoch (1601-01-01) and Unix epoch (1970-01-01)
CHROME_EPOCH_OFFSET = 11644473600

# If no new page is visited within this many minutes, assume the user stepped away
MAX_SESSION_GAP_MINUTES = 30


def chrome_time_to_datetime(chrome_timestamp):
    """Convert Chrome's microseconds-since-1601 timestamp to a Python datetime."""
    unix_seconds = (chrome_timestamp / 1_000_000) - CHROME_EPOCH_OFFSET
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def extract_domain(url):
    """Pull the domain from a URL. e.g. 'https://github.com/user/repo' -> 'github.com'"""
    try:
        without_protocol = url.split("//", 1)[-1]
        domain = without_protocol.split("/")[0].split(":")[0]
        return domain.lower()
    except Exception:
        return ""


def format_duration(minutes):
    """Format a duration in minutes for display. e.g. 1.5 -> '1 min', 65 -> '1h 5min'"""
    minutes = round(minutes)
    if minutes < 1:
        return "< 1 min"
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}min" if mins else f"{hours}h"


def _deduplicate_and_time(raw_visits):
    """
    Clean up raw visit list:
    1. Remove page refreshes — same URL visited again within 30 seconds
    2. Calculate time spent on each page — time until the next visit, capped at MAX_SESSION_GAP_MINUTES
    """
    if not raw_visits:
        return []

    # Step 1: Remove consecutive refreshes (same URL within 30 seconds)
    deduped = [raw_visits[0]]
    for visit in raw_visits[1:]:
        prev = deduped[-1]
        if visit["url"] == prev["url"]:
            t_prev = datetime.fromisoformat(prev["visit_time"])
            t_curr = datetime.fromisoformat(visit["visit_time"])
            if (t_curr - t_prev).total_seconds() < 30:
                continue  # This is just a refresh, skip it
        deduped.append(visit)

    # Step 2: Calculate time spent on each page
    result = []
    for i, visit in enumerate(deduped):
        if i + 1 < len(deduped):
            t1 = datetime.fromisoformat(visit["visit_time"])
            t2 = datetime.fromisoformat(deduped[i + 1]["visit_time"])
            duration_minutes = (t2 - t1).total_seconds() / 60
            # Cap at MAX_SESSION_GAP_MINUTES — if gap is huge, user probably stepped away
            duration_minutes = min(duration_minutes, MAX_SESSION_GAP_MINUTES)
        else:
            duration_minutes = 1.0  # Last visit of the day — assume 1 minute

        result.append({
            **visit,
            "duration_minutes": round(duration_minutes, 1),
            "duration_display": format_duration(duration_minutes),
            "is_meeting": visit.get("is_meeting", 0)
        })

    return result


def get_history(date_str, tracked_domains=None):
    """
    Read and clean Chrome history for a specific date.

    Args:
        date_str: Date in 'YYYY-MM-DD' format
        tracked_domains: List of domains to include (e.g. ['github.com', 'jira.com']).
                         If None or empty, returns ALL domains.

    Returns:
        List of dicts: {url, title, visit_time, domain, duration_minutes, duration_display}
    """
    if not os.path.exists(CHROME_HISTORY_PATH):
        print(f"Chrome history not found at: {CHROME_HISTORY_PATH}")
        return []

    # Copy history file to avoid Chrome's file lock
    temp_history = os.path.join(tempfile.gettempdir(), "chrome_history_copy")
    try:
        shutil.copy2(CHROME_HISTORY_PATH, temp_history)
    except PermissionError:
        print("Could not copy Chrome history. Chrome may be actively writing to it.")
        return []

    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
        return []

    def to_chrome_time(dt):
        return int((dt.timestamp() + CHROME_EPOCH_OFFSET) * 1_000_000)

    chrome_start = to_chrome_time(target_date)
    chrome_end   = to_chrome_time(target_date + timedelta(days=1))

    raw_visits = []
    try:
        conn = sqlite3.connect(temp_history)
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT urls.url, urls.title, visits.visit_time
            FROM visits
            JOIN urls ON urls.id = visits.url
            WHERE visits.visit_time >= ? AND visits.visit_time < ?
            ORDER BY visits.visit_time ASC
        """, (chrome_start, chrome_end)).fetchall()
        conn.close()

        for row in rows:
            url = row["url"]

            # Skip Chrome internal pages
            if url.startswith("chrome://") or url.startswith("chrome-extension://"):
                continue

            domain = extract_domain(url)

            # Filter by tracked keywords — match anywhere in URL or domain
            # e.g. keyword "jira" matches "company.atlassian.net/jira/..." or "jira.company.com"
            if tracked_domains:
                if not any(kw.lower() in url.lower() or kw.lower() in domain for kw in tracked_domains):
                    continue

            visit_dt = chrome_time_to_datetime(row["visit_time"])
            visit_local = visit_dt.astimezone().replace(tzinfo=None)

            is_meeting = any(p in url.lower() for p in MEETING_PATTERNS)

            raw_visits.append({
                "url": url,
                "title": row["title"] or url,
                "visit_time": visit_local.isoformat(timespec="seconds"),
                "domain": domain,
                "is_meeting": 1 if is_meeting else 0
            })

    except Exception as e:
        print(f"Error reading Chrome history: {e}")
    finally:
        try:
            os.remove(temp_history)
        except Exception:
            pass

    # Clean up: remove refreshes and calculate time spent
    cleaned = _deduplicate_and_time(raw_visits)
    print(f"Chrome history: {len(raw_visits)} raw visits → {len(cleaned)} after deduplication.")
    return cleaned


if __name__ == "__main__":
    from datetime import date
    today = date.today().isoformat()
    print(f"Fetching Chrome history for {today}...\n")
    visits = get_history(today)
    for v in visits[:15]:
        print(f"  {v['visit_time']}  [{v['duration_display']:>8}]  {v['domain']}  —  {v['title'][:50]}")
