#!/usr/bin/env python3
"""
Find the specific time entry records causing API discrepancies.

For each discrepancy between single-request and split-request API results,
identifies the individual time tracking entries (with UIDs) on the affected
action cards. This gives Hive support the exact records to investigate.

Output includes:
- Action Card ID and URL
- Individual time entry IDs (UIDs)
- User ID, date, seconds, hours for each entry
- Which entries are on month-end dates (the problematic pattern)
"""

import sys
import csv
import io
import json
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from settings import load_settings
from services.hive_service import HiveService, HiveCredentials
from logger_setup import setup_logger


def parse_csv_string(csv_string):
    if not csv_string:
        return [], []
    reader = csv.DictReader(io.StringIO(csv_string))
    headers = reader.fieldnames or []
    rows = [row for row in reader if row.get("Date")]
    return rows, headers


def make_key(row):
    return (
        row.get("Person", "").strip(),
        row.get("Date", "").strip(),
        row.get("Project", "").strip(),
        row.get("Category", "").strip(),
    )


def get_hours(row):
    val = row.get("Hours", "")
    try:
        return round(float(str(val).replace(",", "")), 2)
    except (ValueError, TypeError):
        return 0.0


def find_discrepancies(single_rows, split_rows):
    """Find rows that differ between single and split requests."""
    lookup_single = {}
    for row in single_rows:
        key = make_key(row)
        if key in lookup_single:
            existing = get_hours(lookup_single[key])
            lookup_single[key]["Hours"] = str(existing + get_hours(row))
        else:
            lookup_single[key] = dict(row)

    lookup_split = {}
    for row in split_rows:
        key = make_key(row)
        if key in lookup_split:
            existing = get_hours(lookup_split[key])
            lookup_split[key]["Hours"] = str(existing + get_hours(row))
        else:
            lookup_split[key] = dict(row)

    discrepancies = []

    # Missing from single request (exist in split only)
    for key, row in lookup_split.items():
        if key not in lookup_single:
            discrepancies.append({
                "type": "missing_from_single",
                "person": key[0], "date": key[1],
                "project": key[2], "category": key[3],
                "hours_single": 0, "hours_split": get_hours(row),
            })

    # Missing from split (exist in single only)
    for key, row in lookup_single.items():
        if key not in lookup_split:
            discrepancies.append({
                "type": "missing_from_split",
                "person": key[0], "date": key[1],
                "project": key[2], "category": key[3],
                "hours_single": get_hours(row), "hours_split": 0,
            })

    # Hours differ
    for key in lookup_single:
        if key in lookup_split:
            h_s = get_hours(lookup_single[key])
            h_sp = get_hours(lookup_split[key])
            if abs(h_s - h_sp) > 0.001:
                discrepancies.append({
                    "type": "hours_differ",
                    "person": key[0], "date": key[1],
                    "project": key[2], "category": key[3],
                    "hours_single": h_s, "hours_split": h_sp,
                })

    return discrepancies


def fetch_raw_time_tracking(hive, from_date, to_date):
    """Fetch raw time tracking data preserving all IDs."""
    print(f"Fetching raw time tracking data ({from_date} to {to_date})...")

    query = """
    query GetTimeTrackingData($workspaceId: ID!, $startDate: Date, $endDate: Date) {
      getTimeTrackingData(workspaceId: $workspaceId, startDate: $startDate, endDate: $endDate) {
        actions {
          _id
          title
          project {
            _id
            name
            parentProject
          }
          timeTracking {
            actualList {
              id
              userId
              time
              date
              description
              automated
              categoryId
            }
            estimate
          }
        }
        projects {
          _id
          name
          parentProject
        }
      }
    }
    """

    variables = {
        "workspaceId": hive.credentials.workspace_id,
        "startDate": from_date.isoformat(),
        "endDate": to_date.isoformat(),
    }

    result = hive._execute_query(query, variables)
    ttd = result.get("getTimeTrackingData", {})
    actions = ttd.get("actions", [])

    user_lookup = hive.get_workspace_users()

    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    # Build a flat list of entries with all IDs preserved
    entries = []
    for action in actions:
        action_id = action.get("_id", "")
        action_title = action.get("title", "")
        project = action.get("project") or {}
        project_id = project.get("_id", "")
        project_name = project.get("name", "")

        tracking = action.get("timeTracking") or {}
        for entry in (tracking.get("actualList") or []):
            uid = entry.get("userId", "")
            user_info = user_lookup.get(uid, {})
            if uid and not user_info:
                user_info = hive.resolve_user(uid)

            raw_date = entry.get("date", "")
            if isinstance(raw_date, str) and "T" in raw_date:
                raw_date = raw_date.split("T")[0]

            if raw_date and not (from_str <= raw_date <= to_str):
                continue

            time_seconds = entry.get("time", 0) or 0

            entries.append({
                "time_entry_id": entry.get("id", ""),
                "action_id": action_id,
                "action_title": action_title,
                "project_id": project_id,
                "project_name": project_name,
                "user_id": uid,
                "user_name": user_info.get("fullName", ""),
                "date": raw_date,
                "time_seconds": time_seconds,
                "time_minutes": round(time_seconds / 60, 2),
                "time_hours": round(time_seconds / 3600, 2),
                "description": entry.get("description", ""),
                "automated": entry.get("automated", False),
                "category_id": entry.get("categoryId", ""),
            })

    print(f"  Retrieved {len(entries)} individual time entries")
    return entries


def is_month_end(date_str):
    """Check if a date string is the last day of its month."""
    try:
        d = date.fromisoformat(date_str)
        if d.month == 12:
            next_month_1st = date(d.year + 1, 1, 1)
        else:
            next_month_1st = date(d.year, d.month + 1, 1)
        last_day = next_month_1st - timedelta(days=1)
        return d == last_day
    except (ValueError, TypeError):
        return False


def main():
    setup_logger()

    settings = load_settings()
    if not settings.is_configured():
        print("ERROR: Settings not configured.")
        sys.exit(1)

    creds = HiveCredentials(
        api_key=settings.hive_api_key,
        user_id=settings.hive_user_id,
        workspace_id=settings.hive_workspace_id,
    )
    hive = HiveService(creds)
    workspace_id = settings.hive_workspace_id

    print("Connecting to Hive API...")
    if not hive.test_connection():
        print("ERROR: Cannot connect to Hive API")
        sys.exit(1)
    print("Connected.\n")

    # --- Run for both 2026 YTD and 2025 ---
    today = date.today()
    ranges = [
        (date(2026, 1, 1), today, "2026 YTD"),
        (date(2025, 1, 1), date(2025, 12, 31), "2025 Full Year"),
    ]

    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    for start_date, end_date, label in ranges:
        print(f"\n{'=' * 70}")
        print(f"  {label}: {start_date} to {end_date}")
        print(f"{'=' * 70}")

        # 1. Fetch single request
        print(f"\nFetching single request ({start_date} to {end_date})...")
        single_csv = hive._fetch_timesheet_csv_string(start_date, end_date)
        single_rows, _ = parse_csv_string(single_csv)
        print(f"  Single: {len(single_rows)} rows")

        # 2. Fetch split monthly requests
        print("Fetching monthly split requests...")
        split_rows = []
        current = start_date
        while current <= end_date:
            if current.month == 12:
                month_end = date(current.year, 12, 31)
            else:
                month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
            month_end = min(month_end, end_date)

            csv_data = hive._fetch_timesheet_csv_string(current, month_end)
            month_rows, _ = parse_csv_string(csv_data)
            split_rows.extend(month_rows)

            if month_end >= end_date:
                break
            current = month_end + timedelta(days=1)
        print(f"  Split: {len(split_rows)} rows")

        # 3. Find discrepancies
        discrepancies = find_discrepancies(single_rows, split_rows)
        print(f"  Discrepancies: {len(discrepancies)}")

        if not discrepancies:
            print("  No discrepancies found!")
            continue

        # 4. Fetch detailed time entries
        all_entries = fetch_raw_time_tracking(hive, start_date, end_date)

        # 5. Index entries by (user_name, date, project_name)
        entry_index = defaultdict(list)
        for e in all_entries:
            key = (e["user_name"].strip(), e["date"].strip(), e["project_name"].strip())
            entry_index[key].append(e)

        # 6. For each discrepancy, find the specific entries
        report_lines = []
        report_lines.append(f"HIVE TIME ENTRY DISCREPANCY — DETAILED RECORD IDs")
        report_lines.append(f"Date Range: {start_date} to {end_date} ({label})")
        report_lines.append(f"Generated: {today}")
        report_lines.append(f"Workspace ID: {workspace_id}")
        report_lines.append(f"")
        report_lines.append(f"Test: Same data queried as one request (full range) vs monthly splits.")
        report_lines.append(f"Single request: {len(single_rows)} rows | Split requests: {len(split_rows)} rows")
        report_lines.append(f"Total discrepancies: {len(discrepancies)}")
        report_lines.append(f"")

        # Collect all problematic entries for the JSON export
        all_problem_entries = []

        # Group discrepancies: missing rows on month-end dates
        missing_month_end = [d for d in discrepancies
                            if d["type"] == "missing_from_single" and is_month_end(d["date"])]
        missing_other = [d for d in discrepancies
                        if d["type"] == "missing_from_single" and not is_month_end(d["date"])]
        hours_diff = [d for d in discrepancies if d["type"] == "hours_differ"]
        missing_from_split = [d for d in discrepancies if d["type"] == "missing_from_split"]

        report_lines.append(f"{'=' * 70}")
        report_lines.append(f"PATTERN SUMMARY")
        report_lines.append(f"{'=' * 70}")
        report_lines.append(f"  Rows missing from single request (month-end dates): {len(missing_month_end)}")
        report_lines.append(f"  Rows missing from single request (other dates): {len(missing_other)}")
        report_lines.append(f"  Rows missing from split requests: {len(missing_from_split)}")
        report_lines.append(f"  Rows with different hours: {len(hours_diff)}")
        report_lines.append(f"")

        # ---- SECTION: Month-end missing rows with full entry details ----
        report_lines.append(f"{'=' * 70}")
        report_lines.append(f"MISSING MONTH-END ENTRIES — Individual Time Entry Records")
        report_lines.append(f"These entries exist in monthly queries but vanish in the full-range query.")
        report_lines.append(f"{'=' * 70}")

        for i, disc in enumerate(sorted(missing_month_end, key=lambda d: (d["date"], d["person"])), 1):
            person = disc["person"]
            dt = disc["date"]
            project = disc["project"]

            matching = entry_index.get((person, dt, project), [])

            report_lines.append(f"")
            report_lines.append(f"  [{i}] {person} | {dt} | {project}")
            if disc["category"]:
                report_lines.append(f"       Category: {disc['category']}")
            report_lines.append(f"       Hours in split request: {disc['hours_split']}")
            report_lines.append(f"       Hours in single request: MISSING")
            report_lines.append(f"       Matching detail time entries: {len(matching)}")

            if matching:
                for e in matching:
                    report_lines.append(f"")
                    report_lines.append(f"       TIME ENTRY RECORD:")
                    report_lines.append(f"         Time Entry ID:  {e['time_entry_id']}")
                    report_lines.append(f"         Action Card ID: {e['action_id']}")
                    report_lines.append(f"         Action Title:   {e['action_title']}")
                    report_lines.append(f"         Action URL:     https://app.hive.com/workspace/{workspace_id}/action-flat/{e['action_id']}")
                    report_lines.append(f"         User ID:        {e['user_id']}")
                    report_lines.append(f"         User Name:      {e['user_name']}")
                    report_lines.append(f"         Date:           {e['date']}")
                    report_lines.append(f"         Time (seconds): {e['time_seconds']}")
                    report_lines.append(f"         Time (minutes): {e['time_minutes']}")
                    report_lines.append(f"         Time (hours):   {e['time_hours']}")
                    report_lines.append(f"         Description:    {e['description'] or '(none)'}")
                    report_lines.append(f"         Automated:      {e['automated']}")
                    report_lines.append(f"         Category ID:    {e['category_id'] or '(none)'}")
                    report_lines.append(f"         Project ID:     {e['project_id']}")

                    all_problem_entries.append({
                        "discrepancy_type": "missing_month_end",
                        "discrepancy_date": dt,
                        "discrepancy_person": person,
                        "discrepancy_project": project,
                        **e,
                        "action_url": f"https://app.hive.com/workspace/{workspace_id}/action-flat/{e['action_id']}",
                    })
            else:
                report_lines.append(f"       ** NO MATCHING ENTRIES IN DETAIL API — entry may be invisible to time tracking endpoint too **")

        # ---- SECTION: Hours differ — show the entries on the inflated dates ----
        report_lines.append(f"")
        report_lines.append(f"{'=' * 70}")
        report_lines.append(f"HOURS DIFFER — Entries where single request shows MORE hours")
        report_lines.append(f"The extra hours likely come from the missing month-end entries above.")
        report_lines.append(f"{'=' * 70}")

        for i, disc in enumerate(sorted(hours_diff, key=lambda d: (d["date"], d["person"])), 1):
            person = disc["person"]
            dt = disc["date"]
            project = disc["project"]
            diff = disc["hours_single"] - disc["hours_split"]

            matching = entry_index.get((person, dt, project), [])

            report_lines.append(f"")
            report_lines.append(f"  [{i}] {person} | {dt} | {project}")
            if disc["category"]:
                report_lines.append(f"       Category: {disc['category']}")
            report_lines.append(f"       Hours single:  {disc['hours_single']}")
            report_lines.append(f"       Hours split:   {disc['hours_split']}")
            report_lines.append(f"       Excess:        +{diff:.2f} hrs")
            report_lines.append(f"       Detail entries: {len(matching)}")

            if matching:
                for e in matching:
                    report_lines.append(f"")
                    report_lines.append(f"       TIME ENTRY RECORD:")
                    report_lines.append(f"         Time Entry ID:  {e['time_entry_id']}")
                    report_lines.append(f"         Action Card ID: {e['action_id']}")
                    report_lines.append(f"         Action Title:   {e['action_title']}")
                    report_lines.append(f"         Action URL:     https://app.hive.com/workspace/{workspace_id}/action-flat/{e['action_id']}")
                    report_lines.append(f"         User ID:        {e['user_id']}")
                    report_lines.append(f"         User Name:      {e['user_name']}")
                    report_lines.append(f"         Date:           {e['date']}")
                    report_lines.append(f"         Time (seconds): {e['time_seconds']}")
                    report_lines.append(f"         Time (minutes): {e['time_minutes']}")
                    report_lines.append(f"         Time (hours):   {e['time_hours']}")
                    report_lines.append(f"         Description:    {e['description'] or '(none)'}")
                    report_lines.append(f"         Automated:      {e['automated']}")
                    report_lines.append(f"         Category ID:    {e['category_id'] or '(none)'}")
                    report_lines.append(f"         Project ID:     {e['project_id']}")

                    all_problem_entries.append({
                        "discrepancy_type": "hours_inflated",
                        "discrepancy_date": dt,
                        "discrepancy_person": person,
                        "discrepancy_project": project,
                        "hours_single_request": disc["hours_single"],
                        "hours_split_request": disc["hours_split"],
                        "excess_hours": round(diff, 2),
                        **e,
                        "action_url": f"https://app.hive.com/workspace/{workspace_id}/action-flat/{e['action_id']}",
                    })

        # Write text report
        report_text = "\n".join(report_lines)
        safe_label = label.replace(" ", "_").lower()
        txt_path = output_dir / f"problem_entries_{safe_label}_{start_date}_{end_date}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"\n  Text report: {txt_path}")

        # Write JSON with all problematic entries (for Hive support)
        json_path = output_dir / f"problem_entries_{safe_label}_{start_date}_{end_date}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "workspace_id": workspace_id,
                "date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
                "label": label,
                "generated": today.isoformat(),
                "summary": {
                    "single_request_rows": len(single_rows),
                    "split_request_rows": len(split_rows),
                    "total_discrepancies": len(discrepancies),
                    "missing_month_end": len(missing_month_end),
                    "missing_other": len(missing_other),
                    "hours_differ": len(hours_diff),
                },
                "problem_entries": all_problem_entries,
            }, f, indent=2, default=str)
        print(f"  JSON report: {json_path}")

        # Print summary to console
        print(f"\n  --- {label} Summary ---")
        print(f"  Missing month-end entries: {len(missing_month_end)}")
        print(f"  Entries with inflated hours: {len(hours_diff)}")
        print(f"  Total problem time entry records: {len(all_problem_entries)}")

        # Print first few examples to console
        print(f"\n  --- Sample Problem Records ---")
        shown = 0
        for e in all_problem_entries[:10]:
            print(f"    Time Entry ID: {e['time_entry_id']}")
            print(f"    Action Card ID: {e['action_id']}")
            print(f"    Action URL: {e['action_url']}")
            print(f"    User: {e['user_name']} (ID: {e['user_id']})")
            print(f"    Date: {e['date']}")
            print(f"    Time: {e['time_seconds']}s = {e['time_hours']} hrs")
            print(f"    Type: {e['discrepancy_type']}")
            print()
            shown += 1
        if len(all_problem_entries) > shown:
            print(f"    ... and {len(all_problem_entries) - shown} more (see report files)")


if __name__ == "__main__":
    main()
