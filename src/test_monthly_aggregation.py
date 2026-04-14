"""Test monthly aggregation against existing production sheet data.

Fetches time entries via getActionsByWorkspace, aggregates by
Person + Project + Category + Month, writes to TEST tabs,
and compares row counts + hour totals against production tabs.

Usage:
    cd HIVE_Extract
    source venv-linux/bin/activate
    python src/test_monthly_aggregation.py [--year 2025] [--write-tabs]

Flags:
    --year YYYY    Year to test (default: 2025)
    --write-tabs   Actually write to _TEST tabs in the spreadsheet
                   (without this flag, only prints comparison)
"""

import argparse
import csv
import io
import sys
from datetime import date
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from settings import load_settings, SHARED_CONFIG_DIR
from services.hive_service import HiveService, HiveCredentials
from services.sheets_service import SheetsService
from config import TABS, YEAR_TABS, TEST_TABS, TEST_YEAR_TABS
from logger_setup import setup_logger, get_logger

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


def read_production_tab_stats(sheets, tab_name):
    """Read row count and total hours from an existing production tab.

    Production tabs have:
    - Row 3: summary (C3="# Rows", D3=count, E3=total hours)
    - Row 5: headers (Person, Email, ..., Hours, ...)
    - Row 6+: data
    """
    try:
        svc = sheets._shared.service
        spreadsheet_id = sheets._shared._default_spreadsheet_id

        # First try to read the summary row (fast path)
        summary = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A3:E3",
        ).execute()
        summary_vals = summary.get("values", [[]])[0]

        if len(summary_vals) >= 5:
            try:
                row_count = int(str(summary_vals[3]).replace(",", ""))
                total_hours = float(str(summary_vals[4]).replace(",", ""))
                return {"rows": row_count, "total_hours": round(total_hours, 2),
                        "source": "summary_row"}
            except (ValueError, IndexError):
                pass

        # Fallback: count data rows and sum Hours column
        result = svc.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A5:AA10000",
        ).execute()
        values = result.get("values", [])

        if not values:
            return {"rows": 0, "total_hours": 0.0, "error": "No data found"}

        # Row 5 = headers (index 0 in result since we start from A5)
        headers = [str(c).strip() for c in values[0]]
        data_rows = values[1:]  # Row 6+ = data

        hours_col = None
        for i, h in enumerate(headers):
            if h.lower() == "hours":
                hours_col = i
                break

        total_hours = 0.0
        valid_rows = 0
        for row in data_rows:
            if not row or not any(str(c).strip() for c in row):
                continue
            valid_rows += 1
            if hours_col is not None and hours_col < len(row):
                try:
                    total_hours += float(str(row[hours_col]).replace(",", ""))
                except (ValueError, TypeError):
                    pass

        return {"rows": valid_rows, "total_hours": round(total_hours, 2),
                "source": "computed"}

    except Exception as e:
        return {"rows": 0, "total_hours": 0.0, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Test monthly aggregation")
    parser.add_argument("--year", type=int, default=2025, help="Year to test")
    parser.add_argument("--write-tabs", action="store_true",
                        help="Write results to TEST tabs in the spreadsheet")
    parser.add_argument("--client", type=str, default="LSC", help="Client key")
    args = parser.parse_args()

    logger = setup_logger()
    logger = get_logger()

    # Load config
    settings = load_settings()
    if not settings.is_configured():
        print("ERROR: Not configured. Run: python src/main.py --setup")
        sys.exit(1)

    master = MasterConfig()
    client_config = master.get_client(args.client)
    hive_cfg = client_config.hive

    hive = HiveService(
        HiveCredentials(
            api_key=settings.hive_api_key,
            user_id=hive_cfg.user_id,
            workspace_id=hive_cfg.workspace_id,
        )
    )

    print(f"Testing Hive connection...")
    if not hive.test_connection():
        print("Failed to connect to Hive API")
        sys.exit(1)
    print("Connected.\n")

    # Set up Sheets
    spreadsheet_id = client_config.sheets.hive_extract_sheet_id
    credential_ref = client_config.client.google_auth_override or "BosOpt"
    sheets = SheetsService(spreadsheet_id, credential_ref=credential_ref)
    if not sheets.authenticate() or not sheets.test_access():
        print("ERROR: Could not connect to Google Sheets")
        sys.exit(1)

    year = args.year
    from_date = date(year, 1, 1)
    to_date = date(year, 12, 31)
    today = date.today()
    if to_date > today:
        to_date = today

    print(f"{'=' * 70}")
    print(f"  MONTHLY AGGREGATION TEST — {year}")
    print(f"  Date range: {from_date} to {to_date}")
    print(f"{'=' * 70}\n")

    # Step 1: Fetch and aggregate
    print("Step 1: Fetching time entries via getActionsByWorkspace...")
    print("        (This takes ~50-60 seconds for full workspace scan)\n")

    monthly_rows = hive.get_time_entries_monthly(from_date, to_date)

    agg_total_hours = round(sum(r["Hours"] for r in monthly_rows), 2)
    agg_row_count = len(monthly_rows)

    print(f"\n  Aggregated result:")
    print(f"    Rows:        {agg_row_count:,}")
    print(f"    Total hours: {agg_total_hours:,.2f}")

    # Step 2: Show breakdown by person
    person_hours = defaultdict(float)
    person_rows = defaultdict(int)
    for r in monthly_rows:
        person_hours[r["Person"]] += r["Hours"]
        person_rows[r["Person"]] += 1

    print(f"\n  By person:")
    print(f"    {'Person':<35s} {'Rows':>6s} {'Hours':>10s}")
    print(f"    {'-' * 35} {'-' * 6} {'-' * 10}")
    for person in sorted(person_hours.keys()):
        print(f"    {person:<35s} {person_rows[person]:>6d} {person_hours[person]:>10,.2f}")

    # Step 3: Show categories found
    categories = sorted(set(r["Category"] for r in monthly_rows))
    print(f"\n  Categories found ({len(categories)}):")
    for cat in categories:
        label = cat if cat else "(none)"
        count = sum(1 for r in monthly_rows if r["Category"] == cat)
        hrs = sum(r["Hours"] for r in monthly_rows if r["Category"] == cat)
        print(f"    {label:<35s} {count:>6d} rows  {hrs:>10,.2f} hrs")

    # Step 4: Compare against production tab
    prod_tab = f"ALL_{year}"
    print(f"\n{'=' * 70}")
    print(f"  COMPARISON vs production tab: {prod_tab}")
    print(f"{'=' * 70}\n")

    prod_stats = read_production_tab_stats(sheets, prod_tab)
    if "error" in prod_stats:
        print(f"  WARNING: Could not read production tab '{prod_tab}': {prod_stats['error']}")
        print(f"  (Tab may not exist or may be empty)")
    else:
        print(f"  {'Source':<35s} {'Rows':>8s} {'Total Hours':>14s}")
        print(f"  {'-' * 35} {'-' * 8} {'-' * 14}")
        print(f"  {'Production (' + prod_tab + ')':<35s} {prod_stats['rows']:>8,d} {prod_stats['total_hours']:>14,.2f}")
        print(f"  {'Aggregated (monthly)':<35s} {agg_row_count:>8,d} {agg_total_hours:>14,.2f}")

        row_diff = agg_row_count - prod_stats["rows"]
        hrs_diff = round(agg_total_hours - prod_stats["total_hours"], 2)
        print(f"\n  Row difference:  {row_diff:+,d}  (aggregated has {'fewer' if row_diff < 0 else 'more'} rows — expected with monthly grouping)")
        print(f"  Hour difference: {hrs_diff:+,.2f}")

        if abs(hrs_diff) < 1.0:
            print(f"\n  RESULT: HOURS MATCH (within 1 hour tolerance)")
        else:
            print(f"\n  RESULT: HOUR MISMATCH — investigate")

    # Also compare against the UI CSV if we have it
    ui_csv_path = Path(__file__).parent.parent / "output" / f"UI Export_Timesheet_Reporting_{year}.csv"
    if ui_csv_path.exists():
        print(f"\n{'=' * 70}")
        print(f"  COMPARISON vs UI CSV: {ui_csv_path.name}")
        print(f"{'=' * 70}\n")

        with open(ui_csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            ui_rows = list(reader)

        ui_total = round(sum(float(r.get("Hours", 0) or 0) for r in ui_rows), 2)
        ui_count = len(ui_rows)

        print(f"  {'Source':<35s} {'Rows':>8s} {'Total Hours':>14s}")
        print(f"  {'-' * 35} {'-' * 8} {'-' * 14}")
        print(f"  {'UI CSV (daily)':<35s} {ui_count:>8,d} {ui_total:>14,.2f}")
        print(f"  {'Aggregated (monthly)':<35s} {agg_row_count:>8,d} {agg_total_hours:>14,.2f}")

        hrs_diff = round(agg_total_hours - ui_total, 2)
        print(f"\n  Row reduction:   {ui_count:,d} daily → {agg_row_count:,d} monthly ({ui_count - agg_row_count:,d} fewer rows)")
        print(f"  Hour difference: {hrs_diff:+,.2f}")

        if abs(hrs_diff) < 1.0:
            print(f"\n  RESULT: HOURS MATCH (within 1 hour tolerance)")
        else:
            print(f"\n  RESULT: HOUR MISMATCH — investigate")

    # Step 5: Write to TEST tabs if requested
    if args.write_tabs:
        test_tab_key = f"ALL_{year}_test"
        test_tab_config = TEST_YEAR_TABS.get(test_tab_key)
        if not test_tab_config:
            print(f"\n  No test tab config for {test_tab_key}")
        else:
            tab_name = test_tab_config["name"]
            header_row = test_tab_config["header_row"]
            data_start_row = test_tab_config["data_start_row"]

            print(f"\n{'=' * 70}")
            print(f"  WRITING to test tab: {tab_name}")
            print(f"{'=' * 70}\n")

            # Clear and write
            sheets.clear_tab_data(tab_name, header_row)
            success, rows_written = sheets.write_data(
                tab_name=tab_name,
                data=monthly_rows,
                data_start_row=data_start_row,
                include_headers=True,
                header_row=header_row,
            )
            if success:
                sheets.update_timestamp(tab_name, cell="C1")
                print(f"  Wrote {rows_written} rows to {tab_name}")
            else:
                print(f"  ERROR writing to {tab_name}")

    print(f"\nDone.")


if __name__ == "__main__":
    main()
