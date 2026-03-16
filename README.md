# Work Tracker

A local web app that gives you a daily timeline of everything you worked on — browser activity, manual tasks, meetings, and notes. Runs entirely on your machine, no cloud required.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Flask](https://img.shields.io/badge/Flask-local-green)

---

## What it does

- **Daily timeline** — see your day at a glance: tasks you logged, websites you visited, and how long you spent on each
- **Browser history sync** — pulls from Chrome's local history, groups visits by domain, and shows time-on-page estimates
- **Meeting detection** — automatically flags Teams, Zoom, Google Meet, and Webex visits as meetings
- **Daily Focus sidebar** — bar chart showing time split across Teams, Outlook, Jira, Qualtrics, Medallia, and other sites
- **EOD standup generator** — one click produces a paste-ready summary for Teams or email
- **Daily notes** — quick notepad saved per day
- **Search** — find any task, page visit, or note across all days
- **Navigate by date** — step backwards through previous days

---

## Screenshots

> Timeline view with grouped browser entries, meeting detection, and the Daily Focus sidebar.

---

## Requirements

- Python 3.10+
- Google Chrome (for browser history sync)
- Windows (Chrome history path is Windows-specific)

---

## Setup

**1. Clone the repo**
```bash
git clone https://github.com/marcabj97/work-tracker.git
cd work-tracker
```

**2. Create a virtual environment and install dependencies**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**3. Run the app**
```bash
python app.py
```

Then open **http://localhost:5000** in your browser.

---

## How to use it

### Syncing browser history
1. Open the app and navigate to today (or any day)
2. Go to **Settings** and add the domain keywords you want to track, e.g.:
   ```
   teams.microsoft.com, outlook.office.com, jira, qualtrics, medallia
   ```
3. Click **Sync This Day** — it reads Chrome's local history file and imports matching visits

> Chrome must be closed or the history file unlocked for the sync to work. The app copies the file to a temp location to avoid conflicts.

### Adding tasks
Click **+ Add Task** to manually log what you worked on. Tasks appear in the timeline alongside browser activity.

### EOD summary
Click **EOD Summary** to see a pre-written standup you can copy into Teams or email. It includes your tasks, meetings, time breakdown, and any notes you wrote.

---

## Project structure

```
work-tracker/
├── app.py               # Flask routes and page logic
├── database.py          # SQLite read/write (work_tracker.db)
├── browser_history.py   # Chrome history reader
├── graph_client.py      # Microsoft Graph API stub (optional, unused by default)
├── requirements.txt
├── templates/
│   ├── base.html        # Shared nav layout
│   ├── index.html       # Daily timeline view
│   ├── search.html      # Search results
│   └── settings.html    # Domain filter settings
└── static/
    └── style.css        # Dark mode UI
```

Data is stored in `work_tracker.db` (SQLite, created automatically on first run). This file is excluded from git — it stays on your machine.

---

## Notes

- No data leaves your machine — everything is stored locally in SQLite
- The `.env` file (if present) is excluded from git
- `work_tracker.db` is excluded from git — each user gets their own local database
