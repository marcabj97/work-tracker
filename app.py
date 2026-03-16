"""
app.py — Flask web application for the Work Tracker.

Run with:  python app.py
Then open: http://localhost:5000
"""

from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import date, datetime, timedelta

import database
import browser_history
from browser_history import format_duration

app = Flask(__name__)
app.secret_key = "work-tracker-secret-key-change-me"

database.init_db()


# ─── KEY SITES FOR SIDEBAR ────────────────────────────────────────────────────
KEY_SITES = [
    ("💬 Teams",     ["teams.microsoft.com", "teams"]),
    ("📧 Outlook",   ["outlook.office", "outlook.live", "outlook.com"]),
    ("🎯 Jira",      ["jira", "atlassian"]),
    ("📋 Qualtrics", ["qualtrics"]),
    ("🏆 Medallia",  ["medallia"]),
]


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def format_time(iso_string):
    if not iso_string:
        return ""
    try:
        parts = iso_string.split(" ")
        return parts[1][:5] if len(parts) >= 2 else iso_string[:5]
    except Exception:
        return iso_string


def group_browser_events(timeline):
    """Merge consecutive browser events with the same domain into a group."""
    result = []
    i = 0
    while i < len(timeline):
        event = timeline[i]
        if event["type"] != "browser":
            result.append(event)
            i += 1
            continue

        domain = event.get("domain", "")
        group = [event]
        j = i + 1
        while (j < len(timeline)
               and timeline[j]["type"] == "browser"
               and timeline[j].get("domain") == domain):
            group.append(timeline[j])
            j += 1

        if len(group) == 1:
            result.append(event)
        else:
            total_min = sum(e.get("duration_minutes", 0) for e in group)
            is_meeting = any(e.get("is_meeting") for e in group)
            result.append({
                "type": "browser_group",
                "domain": domain,
                "time": group[0]["time"],
                "title": domain,
                "pages": group,
                "duration_display": format_duration(total_min),
                "is_meeting": is_meeting,
                "count": len(group),
                "id": None
            })
        i = j
    return result


def compute_site_summary(domain_summary):
    """Map domains to KEY_SITES and compute total minutes + bar widths."""
    totals = {name: 0.0 for name, _ in KEY_SITES}
    other = 0.0

    for row in domain_summary:
        domain = (row["domain"] or "").lower()
        matched = False
        for name, keywords in KEY_SITES:
            if any(kw in domain for kw in keywords):
                totals[name] += row["total_minutes"] or 0
                matched = True
                break
        if not matched:
            other += row["total_minutes"] or 0

    result = [{"name": name, "minutes": totals[name]} for name, _ in KEY_SITES]
    result.append({"name": "🌐 Other", "minutes": other})

    max_minutes = max((r["minutes"] for r in result), default=1) or 1
    total_minutes = sum(r["minutes"] for r in result)
    for r in result:
        r["display"] = format_duration(r["minutes"]) if r["minutes"] >= 1 else "—"
        r["pct"] = round((r["minutes"] / max_minutes) * 100) if r["minutes"] else 0

    return result, format_duration(total_minutes)


def generate_standup(date_str, tasks, meetings, site_summary, total_time, note):
    """Generate a plain-text EOD standup summary ready to paste into Teams/email."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_label = dt.strftime("%A, %d %B %Y")
    except Exception:
        day_label = date_str

    lines = [
        f"EOD Summary — {day_label}",
        "=" * 40,
        "",
    ]

    # Tasks
    lines.append("✅ TASKS COMPLETED")
    if tasks:
        for t in tasks:
            desc = f" — {t['description']}" if t.get("description") else ""
            lines.append(f"  • {t['title']}{desc}")
    else:
        lines.append("  • (none logged)")
    lines.append("")

    # Meetings
    lines.append("🗓️ MEETINGS")
    if meetings:
        for m in meetings:
            lines.append(f"  • {m['title']}  ({format_time(m['visit_time'])})")
    else:
        lines.append("  • (none detected)")
    lines.append("")

    # Time breakdown (only sites with time > 0)
    lines.append("⏱️ TIME BREAKDOWN")
    active = [s for s in site_summary if s["minutes"] >= 1]
    if active:
        for s in active:
            lines.append(f"  • {s['name']}: {s['display']}")
    else:
        lines.append("  • (no browser data)")
    lines.append(f"  Total tracked: {total_time}")
    lines.append("")

    # Notes
    if note and note.strip():
        lines.append("📝 NOTES")
        lines.append(note.strip())
        lines.append("")

    return "\n".join(lines)


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("day_view", date_str=date.today().isoformat()))


@app.route("/day/<date_str>")
def day_view(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for("index"))

    raw_timeline = database.get_day_timeline(date_str)
    timeline     = group_browser_events(raw_timeline)
    tasks        = database.get_tasks_for_date(date_str)
    meetings     = database.get_meetings_for_date(date_str)
    note         = database.get_note(date_str)

    current  = datetime.strptime(date_str, "%Y-%m-%d")
    prev_day = (current - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (current + timedelta(days=1)).strftime("%Y-%m-%d")
    today    = date.today().isoformat()

    counts = {"task": 0, "browser": 0}
    for event in raw_timeline:
        if event["type"] == "task":    counts["task"] += 1
        elif event["type"] == "browser": counts["browser"] += 1

    domain_summary           = database.get_domain_summary(date_str)
    site_summary, total_time = compute_site_summary(domain_summary)

    standup = generate_standup(date_str, tasks, meetings, site_summary, total_time, note)

    return render_template(
        "index.html",
        date_str=date_str, today=today,
        prev_day=prev_day, next_day=next_day,
        timeline=timeline, tasks=tasks,
        meetings=meetings, note=note,
        counts=counts,
        site_summary=site_summary, total_time=total_time,
        standup=standup,
        format_time=format_time
    )


# ─── TASKS ────────────────────────────────────────────────────────────────────

@app.route("/tasks/add", methods=["POST"])
def add_task():
    task_date   = request.form.get("date", date.today().isoformat())
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    if not title:
        flash("Task title is required.", "error")
    else:
        database.add_task(task_date, title, description)
        flash(f'Task "{title}" added.', "success")
    return redirect(url_for("day_view", date_str=task_date))


@app.route("/tasks/delete/<int:task_id>", methods=["POST"])
def delete_task(task_id):
    date_str = request.form.get("date", date.today().isoformat())
    database.delete_task(task_id)
    flash("Task deleted.", "success")
    return redirect(url_for("day_view", date_str=date_str))


# ─── NOTES ────────────────────────────────────────────────────────────────────

@app.route("/notes/save", methods=["POST"])
def save_note():
    note_date = request.form.get("date", date.today().isoformat())
    content   = request.form.get("content", "").strip()
    database.save_note(note_date, content)
    flash("Note saved.", "success")
    return redirect(url_for("day_view", date_str=note_date))


# ─── SYNC ─────────────────────────────────────────────────────────────────────

@app.route("/sync", methods=["POST"])
def sync():
    date_str = request.form.get("date", date.today().isoformat())

    tracked_domains_raw = database.get_setting("tracked_domains", "")
    tracked_domains = [d.strip() for d in tracked_domains_raw.split(",") if d.strip()]

    database.clear_browser_activity_for_date(date_str)
    visits = browser_history.get_history(date_str, tracked_domains or None)
    if visits:
        database.save_browser_activity(visits)
        meetings = sum(1 for v in visits if v.get("is_meeting"))
        msg = f"Imported {len(visits)} browser visits"
        if meetings:
            msg += f" ({meetings} meeting{'s' if meetings != 1 else ''} detected)"
        flash(msg + ".", "success")
    else:
        flash("No browser history found. Make sure Chrome is not locked and domains are set in Settings.", "warning")

    return redirect(url_for("day_view", date_str=date_str))


# ─── SEARCH ───────────────────────────────────────────────────────────────────

@app.route("/search")
def search():
    query   = request.args.get("q", "").strip()
    results = database.search(query) if query else []
    return render_template("search.html", query=query, results=results, format_time=format_time)


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        database.set_setting("tracked_domains", request.form.get("tracked_domains", "").strip())
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", tracked_domains=database.get_setting("tracked_domains", ""))


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting Work Tracker at http://localhost:5000")
    print("Press Ctrl+C to stop.\n")
    app.run(debug=True, port=5000)
