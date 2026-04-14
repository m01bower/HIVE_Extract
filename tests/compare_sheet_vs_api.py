#!/usr/bin/env python3
"""
Compare ALL_2026 Google Sheet tab data against a fresh API pull.

Reads the current ALL_2026 tab from Google Sheets, fetches fresh API
data for the same date range, and compares them row-by-row.
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
from services.sheets_service import SheetsService
from config import SPREADSHEET_ID, YEAR_TABS
from logger_setup import setup_logger


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


def read_sheet_tab(sheets, tab_name, header_row, data_start_row):
    """Read all data from a Google Sheet tab into list of dicts."""
    # Get headers
    headers = sheets.get_tab_headers(tab_name, header_row)
    if not headers:
        print(f"  WARNING: No headers found in {tab_name} row {header_row}")
        return []

    print(f"  Sheet headers: {headers}")

    # Read all data rows
    range_name = f"'{tab_name}'!A{data_start_row}:ZZ"
    result = sheets.sheets.spreadsheets().values().get(
        spreadsheetId=sheets.spreadsheet_id,
        range=range_name,
    ).execute()
    raw_rows = result.get("values", [])

    rows = []
    for raw in raw_rows:
        if not raw:
            continue
        row = {}
        for i, h in enumerate(headers):
            if i < len(raw):
                row[h] = raw[i]
            else:
                row[h] = ""
        # Skip rows without a Date
        if row.get("Date"):
            rows.append(row)

    return rows


def compare_datasets(rows_a, rows_b, label_a, label_b):
    """Compare two datasets and return discrepancies."""
    lookup_a = {}
    for row in rows_a:
        key = make_key(row)
        if key in lookup_a:
            existing = get_hours(lookup_a[key])
            lookup_a[key]["Hours"] = str(existing + get_hours(row))
        else:
            lookup_a[key] = dict(row)

    lookup_b = {}
    for row in rows_b:
        key = make_key(row)
        if key in lookup_b:
            existing = get_hours(lookup_b[key])
            lookup_b[key]["Hours"] = str(existing + get_hours(row))
        else:
            lookup_b[key] = dict(row)

    discrepancies = []

    for key, row in lookup_a.items():
        if key not in lookup_b:
            discrepancies.append({
                "type": f"only_in_{label_a}",
                "person": key[0], "date": key[1],
                "project": key[2], "category": key[3],
                "hours_a": get_hours(row), "hours_b": 0,
            })

    for key, row in lookup_b.items():
        if key not in lookup_a:
            discrepancies.append({
                "type": f"only_in_{label_b}",
                "person": key[0], "date": key[1],
                "project": key[2], "category": key[3],
                "hours_a": 0, "hours_b": get_hours(row),
            })

    for key in lookup_a:
        if key in lookup_b:
            h_a = get_hours(lookup_a[key])
            h_b = get_hours(lookup_b[key])
            if abs(h_a - h_b) > 0.001:
                discrepancies.append({
                    "type": "hours_differ",
                    "person": key[0], "date": key[1],
                    "project": key[2], "category": key[3],
                    "hours_a": h_a, "hours_b": h_b,
                })

    return discrepancies


def fetch_time_tracking_with_ids(hive, from_date, to_date):
    """Fetch detailed time tracking entries with action IDs and time entry IDs."""
    query = """
    query GetTimeTrackingData($workspaceId: ID!, $startDate: Date, $endDate: Date) {
      getTimeTrackingData(workspaceId: $workspaceId, startDate: $startDate, endDate: $endDate) {
        actions {
          _id
          title
          project { _id name parentProject }
          timeTracking {
            actualList { id userId time date description automated categoryId }
          }
        }
        projects { _id name parentProject }
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
    user_lookup = hive.get_workspace_users()

    from_str, to_str = from_date.isoformat(), to_date.isoformat()
    entries = []
    for action in ttd.get("actions", []):
        action_id = action.get("_id", "")
        action_title = action.get("title", "")
        project = action.get("project") or {}
        project_name = project.get("name", "")
        project_id = project.get("_id", "")

        for entry in (action.get("timeTracking") or {}).get("actualList") or []:
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
                "time_hours": round(time_seconds / 3600, 2),
                "description": entry.get("description", ""),
                "automated": entry.get("automated", False),
                "category_id": entry.get("categoryId", ""),
            })
    return entries


def main():
    setup_logger()

    settings = load_settings()
    if not settings.is_configured():
        print("ERROR: Not configured.")
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
        print("ERROR: Cannot connect")
        sys.exit(1)
    print("Connected.\n")

    # Date range: Jan 1 - Feb 17, 2026
    start_date = date(2026, 1, 1)
    end_date = date(2026, 2, 17)
    print(f"Date range: {start_date} to {end_date}\n")

    # ── Step 1: Read ALL_2026 from Google Sheets ──
    print("=" * 70)
    print("STEP 1: Reading ALL_2026 tab from Google Sheets")
    print("=" * 70)

    sheets = SheetsService(SPREADSHEET_ID)
    if not sheets.authenticate():
        print("ERROR: Google Sheets auth failed")
        sys.exit(1)

    tab_config = YEAR_TABS.get("ALL_2026", {"name": "ALL_2026", "header_row": 5, "data_start_row": 6})
    sheet_rows = read_sheet_tab(
        sheets,
        tab_config["name"],
        tab_config["header_row"],
        tab_config["data_start_row"],
    )
    # Filter to our date range
    sheet_rows = [r for r in sheet_rows
                  if r.get("Date", "") >= start_date.isoformat()
                  and r.get("Date", "") <= end_date.isoformat()]
    sheet_total = sum(get_hours(r) for r in sheet_rows)
    print(f"  ALL_2026 sheet: {len(sheet_rows)} rows, {sheet_total:.2f} total hours")
    print(f"  Date range in sheet: {min((r['Date'] for r in sheet_rows), default='N/A')} to {max((r['Date'] for r in sheet_rows), default='N/A')}")

    # ── Step 2: Fetch fresh API data ──
    print(f"\n{'=' * 70}")
    print("STEP 2: Fetching fresh API data (single request)")
    print("=" * 70)

    api_csv = hive._fetch_timesheet_csv_string(start_date, end_date)
    reader = csv.DictReader(io.StringIO(api_csv))
    api_headers = reader.fieldnames or []
    api_rows = [r for r in reader if r.get("Date")
                and r["Date"] >= start_date.isoformat()
                and r["Date"] <= end_date.isoformat()]
    api_total = sum(get_hours(r) for r in api_rows)
    print(f"  Fresh API: {len(api_rows)} rows, {api_total:.2f} total hours")
    print(f"  API columns: {api_headers}")

    # Save fresh API CSV
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    api_csv_path = output_dir / f"api_fresh_2026_{start_date}_{end_date}.csv"
    with open(api_csv_path, "w", encoding="utf-8") as f:
        f.write(api_csv)
    print(f"  Saved to: {api_csv_path}")

    # ── Step 3: Compare ──
    print(f"\n{'=' * 70}")
    print("STEP 3: Comparing ALL_2026 Sheet vs Fresh API")
    print("=" * 70)

    discrepancies = compare_datasets(sheet_rows, api_rows, "Sheet", "API")

    only_sheet = [d for d in discrepancies if d["type"] == "only_in_Sheet"]
    only_api = [d for d in discrepancies if d["type"] == "only_in_API"]
    hours_diff = [d for d in discrepancies if d["type"] == "hours_differ"]

    print(f"\n  Sheet rows: {len(sheet_rows)}")
    print(f"  API rows:   {len(api_rows)}")
    print(f"  Sheet total hours: {sheet_total:.2f}")
    print(f"  API total hours:   {api_total:.2f}")
    print(f"  Hour difference:   {sheet_total - api_total:.2f}")
    print(f"\n  Discrepancies: {len(discrepancies)}")
    print(f"    Only in Sheet: {len(only_sheet)}")
    print(f"    Only in API:   {len(only_api)}")
    print(f"    Hours differ:  {len(hours_diff)}")

    if not discrepancies:
        print("\n  Sheet and API match perfectly!")
        return

    # ── Step 4: Get action card details for discrepancies ──
    print(f"\n{'=' * 70}")
    print("STEP 4: Finding Action Cards for discrepant entries")
    print("=" * 70)

    print(f"\nFetching detailed time tracking data...")
    time_entries = fetch_time_tracking_with_ids(hive, start_date, end_date)
    print(f"  {len(time_entries)} detail entries retrieved")

    # Index by (person, date, project)
    entry_index = defaultdict(list)
    for e in time_entries:
        key = (e["user_name"].strip(), e["date"].strip(), e["project_name"].strip())
        entry_index[key].append(e)

    # Build results
    all_results = []
    for disc in discrepancies:
        matching = entry_index.get((disc["person"], disc["date"], disc["project"]), [])
        action_cards = {}
        for e in matching:
            aid = e["action_id"]
            if aid not in action_cards:
                action_cards[aid] = {
                    "action_id": aid,
                    "action_title": e["action_title"],
                    "url": f"https://app.hive.com/workspace/{workspace_id}/action-flat/{aid}",
                    "entries": [],
                }
            action_cards[aid]["entries"].append(e)
        all_results.append({**disc, "action_cards": list(action_cards.values()), "detail_entries": matching})

    # ── Print Results ──
    print(f"\n{'=' * 70}")
    print("DISCREPANCY DETAILS")
    print("=" * 70)

    for i, r in enumerate(sorted(all_results, key=lambda x: (x["date"], x["person"])), 1):
        diff_str = ""
        if r["type"] == "hours_differ":
            diff = r["hours_a"] - r["hours_b"]
            diff_str = f" | Sheet: {r['hours_a']:.2f} | API: {r['hours_b']:.2f} | Diff: {diff:+.2f}"
        elif r["type"] == "only_in_Sheet":
            diff_str = f" | Sheet: {r['hours_a']:.2f} hrs | NOT in API"
        elif r["type"] == "only_in_API":
            diff_str = f" | NOT in Sheet | API: {r['hours_b']:.2f} hrs"

        print(f"\n  [{i}] {r['person']} | {r['date']} | {r['project']}")
        if r["category"]:
            print(f"       Category: {r['category']}")
        print(f"       {r['type']}{diff_str}")
        print(f"       Detail time entries: {len(r['detail_entries'])}")

        for ac in r["action_cards"]:
            print(f"       Action: {ac['action_title']} ({ac['action_id']})")
            print(f"         URL: {ac['url']}")
            for e in ac["entries"]:
                print(f"         Entry ID: {e['time_entry_id']} | {e['time_hours']} hrs | {e['date']} | auto={e['automated']}")

    # ── Summary URLs ──
    all_urls = set()
    for r in all_results:
        for ac in r["action_cards"]:
            all_urls.add(ac["url"])

    if all_urls:
        print(f"\n{'=' * 70}")
        print(f"ALL AFFECTED ACTION CARD URLs ({len(all_urls)})")
        print("=" * 70)
        for url in sorted(all_urls):
            print(f"  {url}")

    # ── Save JSON ──
    json_path = output_dir / f"sheet_vs_api_2026_{start_date}_{end_date}.json"
    problem_entries = []
    for r in all_results:
        for ac in r["action_cards"]:
            for e in ac["entries"]:
                problem_entries.append({
                    "discrepancy_type": r["type"],
                    "discrepancy_person": r["person"],
                    "discrepancy_date": r["date"],
                    "discrepancy_project": r["project"],
                    "hours_sheet": r["hours_a"],
                    "hours_api": r["hours_b"],
                    **e,
                    "action_url": ac["url"],
                })

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "workspace_id": workspace_id,
            "date_range": {"start": str(start_date), "end": str(end_date)},
            "generated": str(date.today()),
            "summary": {
                "sheet_rows": len(sheet_rows),
                "api_rows": len(api_rows),
                "sheet_total_hours": round(sheet_total, 2),
                "api_total_hours": round(api_total, 2),
                "discrepancies": len(discrepancies),
                "only_in_sheet": len(only_sheet),
                "only_in_api": len(only_api),
                "hours_differ": len(hours_diff),
            },
            "problem_entries": problem_entries,
        }, f, indent=2, default=str)
    print(f"\nJSON report saved: {json_path}")


if __name__ == "__main__":
    main()
