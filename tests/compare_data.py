#!/usr/bin/env python3
"""
Compare Hive API timesheet data and identify discrepant Action Cards.

Tests:
1. API self-consistency (single request vs monthly split requests)
2. API vs Web UI CSV (if a CSV file path is provided)

For all discrepancies, retrieves the underlying Action Card IDs
from the detailed Time Tracking API and outputs Hive URLs.

Usage:
  python tests/compare_data.py
  python tests/compare_data.py --web-ui-csv /path/to/hive_export.csv
  python tests/compare_data.py --year 2025
  python tests/compare_data.py --start 2026-01-01 --end 2026-02-18
"""

import sys
import csv
import io
import argparse
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from settings import load_settings
from services.hive_service import HiveService, HiveCredentials
from logger_setup import setup_logger


# ------------------------------------------------------------------
# CSV parsing
# ------------------------------------------------------------------

def parse_csv_string(csv_string):
    """Parse CSV string into list of dicts, skipping rows without a Date."""
    if not csv_string:
        return [], []
    reader = csv.DictReader(io.StringIO(csv_string))
    headers = reader.fieldnames or []
    rows = []
    for row in reader:
        if row.get("Date"):
            rows.append(row)
    return rows, headers


def load_csv_file(filepath):
    """Load a CSV file from disk."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = [row for row in reader if row.get("Date")]
    return rows, headers


# ------------------------------------------------------------------
# Comparison helpers
# ------------------------------------------------------------------

def make_key(row):
    """Composite key: (Person, Date, Project, Category)."""
    return (
        row.get("Person", "").strip(),
        row.get("Date", "").strip(),
        row.get("Project", "").strip(),
        row.get("Category", "").strip(),
    )


def detect_hours_column(headers):
    """Find the hours column name."""
    for candidate in ["Total Hours", "Hours", "Total"]:
        if candidate in headers:
            return candidate
    # Fallback: look for any column with "hour" in the name
    for h in headers:
        if "hour" in h.lower():
            return h
    return None


def get_hours(row, hours_col):
    """Extract hours value from a row."""
    val = row.get(hours_col, "")
    if val:
        try:
            return round(float(str(val).replace(",", "")), 2)
        except (ValueError, TypeError):
            pass
    return 0.0


def compare_datasets(rows_a, rows_b, headers_a, headers_b, label_a, label_b):
    """Compare two datasets and return discrepancies."""
    hours_col_a = detect_hours_column(headers_a)
    hours_col_b = detect_hours_column(headers_b)

    if not hours_col_a:
        print(f"WARNING: Could not find hours column in {label_a}. Headers: {headers_a}")
        return []
    if not hours_col_b:
        print(f"WARNING: Could not find hours column in {label_b}. Headers: {headers_b}")
        return []

    print(f"  Hours column in {label_a}: '{hours_col_a}'")
    print(f"  Hours column in {label_b}: '{hours_col_b}'")

    # Build lookups by key
    lookup_a = {}
    dupes_a = 0
    for row in rows_a:
        key = make_key(row)
        if key in lookup_a:
            dupes_a += 1
            # Merge by summing hours
            existing_hrs = get_hours(lookup_a[key], hours_col_a)
            new_hrs = get_hours(row, hours_col_a)
            lookup_a[key][hours_col_a] = str(existing_hrs + new_hrs)
        else:
            lookup_a[key] = dict(row)

    lookup_b = {}
    dupes_b = 0
    for row in rows_b:
        key = make_key(row)
        if key in lookup_b:
            dupes_b += 1
            existing_hrs = get_hours(lookup_b[key], hours_col_b)
            new_hrs = get_hours(row, hours_col_b)
            lookup_b[key][hours_col_b] = str(existing_hrs + new_hrs)
        else:
            lookup_b[key] = dict(row)

    if dupes_a:
        print(f"  NOTE: {dupes_a} duplicate keys in {label_a} (hours summed)")
    if dupes_b:
        print(f"  NOTE: {dupes_b} duplicate keys in {label_b} (hours summed)")

    discrepancies = []

    # Rows in A but not B
    for key, row in lookup_a.items():
        if key not in lookup_b:
            discrepancies.append({
                "type": f"missing_from_{label_b}",
                "person": key[0],
                "date": key[1],
                "project": key[2],
                "category": key[3],
                "hours_a": get_hours(row, hours_col_a),
                "hours_b": 0,
            })

    # Rows in B but not A
    for key, row in lookup_b.items():
        if key not in lookup_a:
            discrepancies.append({
                "type": f"missing_from_{label_a}",
                "person": key[0],
                "date": key[1],
                "project": key[2],
                "category": key[3],
                "hours_a": 0,
                "hours_b": get_hours(row, hours_col_b),
            })

    # Rows in both but with different hours
    for key in lookup_a:
        if key in lookup_b:
            hrs_a = get_hours(lookup_a[key], hours_col_a)
            hrs_b = get_hours(lookup_b[key], hours_col_b)
            if abs(hrs_a - hrs_b) > 0.001:
                discrepancies.append({
                    "type": "hours_differ",
                    "person": key[0],
                    "date": key[1],
                    "project": key[2],
                    "category": key[3],
                    "hours_a": hrs_a,
                    "hours_b": hrs_b,
                })

    return discrepancies


# ------------------------------------------------------------------
# Time tracking detail — fetch with action IDs
# ------------------------------------------------------------------

def fetch_time_tracking_with_action_ids(hive, from_date, to_date):
    """Fetch detailed time tracking entries including action IDs.

    Returns list of dicts with: Project, Time Tracked By,
    Time Tracked Date, Tracked (Minutes), Action Title, Action ID.
    """
    print(f"\nFetching detailed time tracking data ({from_date} to {to_date})...")

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
          labels
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

    # Build project lookups
    project_name_lookup = {}
    for p in ttd.get("projects", []):
        project_name_lookup[p.get("_id", "")] = p.get("name", "")

    user_lookup = hive.get_workspace_users()

    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    entries = []
    for action in actions:
        action_id = action.get("_id", "")
        action_title = action.get("title", "")
        project = action.get("project") or {}
        project_name = project.get("name", "")

        tracking = action.get("timeTracking") or {}
        actual_list = tracking.get("actualList") or []

        for entry in actual_list:
            uid = entry.get("userId", "")
            user_info = user_lookup.get(uid, {})
            if uid and not user_info:
                user_info = hive.resolve_user(uid)

            time_seconds = entry.get("time", 0) or 0
            tracked_minutes = round(time_seconds / 60, 2)

            raw_date = entry.get("date", "")
            if isinstance(raw_date, str) and "T" in raw_date:
                raw_date = raw_date.split("T")[0]

            # Filter to date range
            if raw_date and not (from_str <= raw_date <= to_str):
                continue

            entries.append({
                "Action ID": action_id,
                "Action Title": action_title,
                "Project": project_name,
                "Time Tracked By": user_info.get("fullName", ""),
                "Time Tracked Date": raw_date,
                "Tracked (Minutes)": tracked_minutes,
                "Tracked (Hours)": round(tracked_minutes / 60, 2),
                "Description": entry.get("description", ""),
                "Time Entry ID": entry.get("id", ""),
            })

    print(f"  Retrieved {len(entries)} detailed time entries with action IDs")
    return entries


# ------------------------------------------------------------------
# Map discrepancies to action cards
# ------------------------------------------------------------------

def find_action_cards_for_discrepancies(discrepancies, time_entries, workspace_id):
    """For each discrepancy, find the action cards from the detail data."""
    # Index entries by (person, date, project)
    entry_index = defaultdict(list)
    for entry in time_entries:
        key = (
            entry["Time Tracked By"].strip(),
            entry["Time Tracked Date"].strip(),
            entry["Project"].strip(),
        )
        entry_index[key].append(entry)

    results = []
    for disc in discrepancies:
        person = disc["person"]
        dt = disc["date"]
        project = disc["project"]

        # Look up matching detail entries
        matching = entry_index.get((person, dt, project), [])

        # Collect unique action cards
        action_cards = {}
        total_detail_hours = 0
        for e in matching:
            aid = e["Action ID"]
            total_detail_hours += e["Tracked (Hours)"]
            if aid not in action_cards:
                action_cards[aid] = {
                    "id": aid,
                    "title": e["Action Title"],
                    "url": f"https://app.hive.com/workspace/{workspace_id}/action-flat/{aid}",
                    "hours": 0,
                    "entries": [],
                }
            action_cards[aid]["hours"] += e["Tracked (Hours)"]
            action_cards[aid]["entries"].append(e)

        results.append({
            **disc,
            "detail_total_hours": round(total_detail_hours, 2),
            "action_cards": list(action_cards.values()),
            "detail_entry_count": len(matching),
        })

    return results


# ------------------------------------------------------------------
# Report output
# ------------------------------------------------------------------

def print_summary(label_a, label_b, rows_a, rows_b, discrepancies):
    """Print comparison summary."""
    total_a = sum(get_hours(r, detect_hours_column(list(r.keys())) or "Total Hours") for r in rows_a)
    total_b = sum(get_hours(r, detect_hours_column(list(r.keys())) or "Total Hours") for r in rows_b)

    print(f"\n  {label_a}: {len(rows_a)} rows")
    print(f"  {label_b}: {len(rows_b)} rows")
    print(f"  Discrepancies found: {len(discrepancies)}")

    missing_from_b = [d for d in discrepancies if "missing" in d["type"] and label_b.replace(" ", "_") in d["type"]]
    missing_from_a = [d for d in discrepancies if "missing" in d["type"] and label_a.replace(" ", "_") in d["type"]]
    hours_diff = [d for d in discrepancies if d["type"] == "hours_differ"]

    if missing_from_b:
        print(f"    Rows in {label_a} but not {label_b}: {len(missing_from_b)}")
    if missing_from_a:
        print(f"    Rows in {label_b} but not {label_a}: {len(missing_from_a)}")
    if hours_diff:
        print(f"    Rows with different hours: {len(hours_diff)}")


def print_discrepancy_report(results, label_a, label_b, workspace_id):
    """Print detailed discrepancy report with action card URLs."""
    if not results:
        print("\n  No discrepancies found!")
        return

    print(f"\n{'─' * 80}")
    print(f"DISCREPANT RECORDS — {label_a} vs {label_b}")
    print(f"{'─' * 80}")

    # Group by type
    missing = [r for r in results if "missing" in r["type"]]
    different = [r for r in results if r["type"] == "hours_differ"]

    if missing:
        print(f"\n{'━' * 40}")
        print(f"MISSING ROWS ({len(missing)})")
        print(f"{'━' * 40}")
        for i, r in enumerate(missing, 1):
            print(f"\n  [{i}] {r['type']}")
            print(f"      Person:   {r['person']}")
            print(f"      Date:     {r['date']}")
            print(f"      Project:  {r['project']}")
            if r['category']:
                print(f"      Category: {r['category']}")
            print(f"      Hours ({label_a}): {r['hours_a']}")
            print(f"      Hours ({label_b}): {r['hours_b']}")
            print(f"      Detail entries found: {r['detail_entry_count']}")
            if r["action_cards"]:
                print(f"      Action Cards ({len(r['action_cards'])}):")
                for ac in r["action_cards"]:
                    print(f"        - {ac['title']} ({ac['hours']:.2f} hrs)")
                    print(f"          {ac['url']}")
            else:
                print(f"      ⚠ No matching action cards found in detail data")

    if different:
        print(f"\n{'━' * 40}")
        print(f"ROWS WITH DIFFERENT HOURS ({len(different)})")
        print(f"{'━' * 40}")
        for i, r in enumerate(different, 1):
            diff = r["hours_a"] - r["hours_b"]
            print(f"\n  [{i}] {r['person']} | {r['date']} | {r['project']}")
            if r['category']:
                print(f"       Category: {r['category']}")
            print(f"       {label_a}: {r['hours_a']:.2f} hrs")
            print(f"       {label_b}: {r['hours_b']:.2f} hrs")
            print(f"       Difference: {diff:+.2f} hrs")
            print(f"       Detail API total: {r['detail_total_hours']:.2f} hrs")
            print(f"       Detail entries: {r['detail_entry_count']}")
            if r["action_cards"]:
                print(f"       Action Cards ({len(r['action_cards'])}):")
                for ac in r["action_cards"]:
                    print(f"         - {ac['title']} ({ac['hours']:.2f} hrs)")
                    print(f"           {ac['url']}")
            else:
                print(f"       ⚠ No matching action cards found in detail data")

    # Summary of all action card URLs
    all_urls = set()
    for r in results:
        for ac in r["action_cards"]:
            all_urls.add(ac["url"])

    if all_urls:
        print(f"\n{'━' * 40}")
        print(f"ALL AFFECTED ACTION CARD URLs ({len(all_urls)})")
        print(f"{'━' * 40}")
        for url in sorted(all_urls):
            print(f"  {url}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compare Hive timesheet data and find discrepant Action Cards"
    )
    parser.add_argument(
        "--web-ui-csv",
        type=str,
        help="Path to a CSV file downloaded from Hive web UI for comparison",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Year to compare (e.g. 2025). Default: current year YTD",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD). Default: Jan 1 of --year or current year",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD). Default: today",
    )
    args = parser.parse_args()

    setup_logger()

    # Load settings
    settings = load_settings()
    if not settings.is_configured():
        print("ERROR: Settings not configured. Run: python src/main.py --setup")
        sys.exit(1)

    creds = HiveCredentials(
        api_key=settings.hive_api_key,
        user_id=settings.hive_user_id,
        workspace_id=settings.hive_workspace_id,
    )
    hive = HiveService(creds)
    workspace_id = settings.hive_workspace_id

    # Test connection
    print("Connecting to Hive API...")
    if not hive.test_connection():
        print("ERROR: Cannot connect to Hive API")
        sys.exit(1)
    print("Connected successfully.\n")

    # Determine date range
    today = date.today()
    if args.year:
        start_date = date(args.year, 1, 1)
        end_date = date(args.year, 12, 31) if args.year < today.year else today
    else:
        start_date = date(today.year, 1, 1)
        end_date = today

    if args.start:
        start_date = date.fromisoformat(args.start)
    if args.end:
        end_date = date.fromisoformat(args.end)

    print(f"Date range: {start_date} to {end_date}")

    # ================================================================
    # TEST 1: API Self-Consistency
    # ================================================================
    print(f"\n{'=' * 70}")
    print(f"TEST 1: API Self-Consistency (single request vs monthly split)")
    print(f"{'=' * 70}")

    # Single request
    print(f"\nFetching single request ({start_date} to {end_date})...")
    single_csv = hive._fetch_timesheet_csv_string(start_date, end_date)
    single_rows, single_headers = parse_csv_string(single_csv)
    print(f"  Got {len(single_rows)} rows, columns: {single_headers}")

    # Save single-request CSV for reference
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    single_csv_path = output_dir / f"api_single_{start_date}_{end_date}.csv"
    with open(single_csv_path, "w", encoding="utf-8") as f:
        f.write(single_csv)
    print(f"  Saved to: {single_csv_path}")

    # Monthly split requests
    print(f"\nFetching monthly split requests...")
    split_csv_combined = ""
    split_rows = []
    split_headers = []
    current = start_date
    while current <= end_date:
        # End of this month or end_date, whichever is sooner
        if current.month == 12:
            month_end = date(current.year, 12, 31)
        else:
            month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
        month_end = min(month_end, end_date)

        print(f"  Requesting {current} to {month_end}...")
        month_csv = hive._fetch_timesheet_csv_string(current, month_end)
        month_rows, month_headers = parse_csv_string(month_csv)
        print(f"    Got {len(month_rows)} rows")

        if not split_headers and month_headers:
            split_headers = month_headers
        split_rows.extend(month_rows)

        # Next month
        if month_end >= end_date:
            break
        current = month_end + timedelta(days=1)

    print(f"  Combined: {len(split_rows)} rows")

    # Compare
    print(f"\nComparing...")
    discrepancies_self = compare_datasets(
        single_rows, split_rows,
        single_headers, split_headers,
        "Single Request", "Split Requests"
    )
    print_summary("Single Request", "Split Requests", single_rows, split_rows, discrepancies_self)

    # ================================================================
    # TEST 2: API vs Web UI CSV (if provided)
    # ================================================================
    discrepancies_webui = []
    if args.web_ui_csv:
        print(f"\n{'=' * 70}")
        print(f"TEST 2: API vs Web UI CSV")
        print(f"{'=' * 70}")

        csv_path = Path(args.web_ui_csv)
        if not csv_path.exists():
            print(f"ERROR: File not found: {csv_path}")
        else:
            print(f"\nLoading web UI CSV: {csv_path}")
            webui_rows, webui_headers = load_csv_file(csv_path)
            print(f"  Got {len(webui_rows)} rows, columns: {webui_headers}")

            print(f"\nComparing API (single request) vs Web UI CSV...")
            discrepancies_webui = compare_datasets(
                webui_rows, single_rows,
                webui_headers, single_headers,
                "Web UI", "API"
            )
            print_summary("Web UI", "API", webui_rows, single_rows, discrepancies_webui)

    # ================================================================
    # Fetch detailed time tracking data for action card URLs
    # ================================================================
    all_discrepancies = discrepancies_self + discrepancies_webui

    if all_discrepancies:
        time_entries = fetch_time_tracking_with_action_ids(hive, start_date, end_date)

        # Map discrepancies to action cards
        if discrepancies_self:
            print(f"\n{'=' * 70}")
            print(f"RESULTS: API Self-Consistency Discrepancies")
            print(f"{'=' * 70}")
            results_self = find_action_cards_for_discrepancies(
                discrepancies_self, time_entries, workspace_id
            )
            print_discrepancy_report(results_self, "Single Request", "Split Requests", workspace_id)

        if discrepancies_webui:
            print(f"\n{'=' * 70}")
            print(f"RESULTS: API vs Web UI Discrepancies")
            print(f"{'=' * 70}")
            results_webui = find_action_cards_for_discrepancies(
                discrepancies_webui, time_entries, workspace_id
            )
            print_discrepancy_report(results_webui, "Web UI", "API", workspace_id)

        # Write results to file
        report_path = output_dir / f"discrepancy_report_{start_date}_{end_date}.txt"
        import contextlib
        with open(report_path, "w", encoding="utf-8") as f:
            with contextlib.redirect_stdout(f):
                print(f"Hive Timesheet Data Discrepancy Report")
                print(f"Date Range: {start_date} to {end_date}")
                print(f"Generated: {today}")
                print(f"Workspace: {workspace_id}")

                if discrepancies_self:
                    print(f"\n{'=' * 70}")
                    print(f"API Self-Consistency Discrepancies")
                    print(f"{'=' * 70}")
                    results_self = find_action_cards_for_discrepancies(
                        discrepancies_self, time_entries, workspace_id
                    )
                    print_discrepancy_report(results_self, "Single Request", "Split Requests", workspace_id)

                if discrepancies_webui:
                    print(f"\n{'=' * 70}")
                    print(f"API vs Web UI Discrepancies")
                    print(f"{'=' * 70}")
                    results_webui = find_action_cards_for_discrepancies(
                        discrepancies_webui, time_entries, workspace_id
                    )
                    print_discrepancy_report(results_webui, "Web UI", "API", workspace_id)

        print(f"\n\nFull report saved to: {report_path}")
    else:
        print(f"\n{'=' * 70}")
        print("NO DISCREPANCIES FOUND")
        print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
