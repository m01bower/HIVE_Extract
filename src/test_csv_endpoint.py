"""Test the getTimesheetReportingCsvExportData endpoint after Hive's fix.

Pulls CSV data for multiple date ranges, saves raw CSVs, and prints
summary stats (row counts, total hours) for comparison against a
manual web UI download.

Usage:
    python src/test_csv_endpoint.py
"""

import csv
import io
import sys
from datetime import date
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from settings import load_settings, SHARED_CONFIG_DIR
from services.hive_service import HiveService, HiveCredentials
from config import HIVE_GRAPHQL_URL

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def save_csv(filename: str, csv_string: str) -> Path:
    """Save raw CSV string to output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write(csv_string)
    return filepath


def analyze_csv(csv_string: str, label: str) -> dict:
    """Parse CSV and print summary stats."""
    if not csv_string:
        print(f"\n  [{label}] EMPTY RESPONSE — no data returned")
        return {}

    reader = csv.DictReader(io.StringIO(csv_string))
    rows = list(reader)
    headers = reader.fieldnames or []

    # Find the hours column — Hive uses "Hours" in the reporting CSV
    hours_col = None
    for h in headers:
        if h.lower() in ("hours", "total hours", "tracked hours"):
            hours_col = h
            break

    total_hours = 0.0
    person_hours = defaultdict(float)
    date_range = {"min": None, "max": None}

    for row in rows:
        # Sum hours
        if hours_col:
            try:
                h = float(row.get(hours_col, 0) or 0)
                total_hours += h
                person = row.get("Person", row.get("Name", "Unknown"))
                person_hours[person] += h
            except (ValueError, TypeError):
                pass

        # Track date range
        row_date = row.get("Date", "")
        if row_date:
            if date_range["min"] is None or row_date < date_range["min"]:
                date_range["min"] = row_date
            if date_range["max"] is None or row_date > date_range["max"]:
                date_range["max"] = row_date

    stats = {
        "rows": len(rows),
        "columns": headers,
        "total_hours": round(total_hours, 2),
        "person_hours": dict(person_hours),
        "date_range": date_range,
    }

    print(f"\n  {'=' * 60}")
    print(f"  {label}")
    print(f"  {'=' * 60}")
    print(f"  Rows:         {len(rows)}")
    print(f"  Columns:      {len(headers)}")
    print(f"  Column names: {', '.join(headers)}")
    if hours_col:
        print(f"  Hours column: '{hours_col}'")
        print(f"  Total hours:  {total_hours:,.2f}")
    else:
        print(f"  Hours column: NOT FOUND (check column names above)")
    print(f"  Date range:   {date_range['min']} to {date_range['max']}")

    if person_hours:
        print(f"\n  Hours by person:")
        for person in sorted(person_hours.keys()):
            print(f"    {person:<35} {person_hours[person]:>10,.2f}")

    return stats


def run_consistency_test(hive: HiveService):
    """Test internal consistency: single request vs split requests for 2026 YTD.

    This was one of the bugs — asking for Jan-Feb in one request vs two
    returned different hour values.
    """
    print(f"\n{'#' * 60}")
    print(f"#  CONSISTENCY TEST: Single vs Split requests (2026)")
    print(f"{'#' * 60}")

    today = date.today()
    start = date(2026, 1, 1)

    # Single request: Jan 1 to today
    print(f"\n  Fetching single request: {start} to {today}...")
    csv_single = hive.get_timesheet_report_csv_raw(start, today)
    stats_single = analyze_csv(csv_single, f"Single request: {start} to {today}")

    # Split: Jan, then Feb 1 to today
    jan_end = date(2026, 1, 31)
    feb_start = date(2026, 2, 1)

    print(f"\n  Fetching split request: {start} to {jan_end}...")
    csv_jan = hive.get_timesheet_report_csv_raw(start, jan_end)
    stats_jan = analyze_csv(csv_jan, f"Split part 1: {start} to {jan_end}")

    print(f"\n  Fetching split request: {feb_start} to {today}...")
    csv_rest = hive.get_timesheet_report_csv_raw(feb_start, today)
    stats_rest = analyze_csv(csv_rest, f"Split part 2: {feb_start} to {today}")

    # Compare
    if stats_single and stats_jan and stats_rest:
        combined_rows = stats_jan["rows"] + stats_rest["rows"]
        combined_hours = round(stats_jan["total_hours"] + stats_rest["total_hours"], 2)

        print(f"\n  {'=' * 60}")
        print(f"  CONSISTENCY COMPARISON")
        print(f"  {'=' * 60}")
        print(f"  {'Method':<35} {'Rows':>8} {'Hours':>12}")
        print(f"  {'-' * 35} {'-' * 8} {'-' * 12}")
        print(f"  {'Single request':<35} {stats_single['rows']:>8} {stats_single['total_hours']:>12,.2f}")
        print(f"  {'Split (Jan + Feb-today) combined':<35} {combined_rows:>8} {combined_hours:>12,.2f}")

        row_diff = stats_single["rows"] - combined_rows
        hour_diff = round(stats_single["total_hours"] - combined_hours, 2)
        if row_diff == 0 and hour_diff == 0.0:
            print(f"\n  RESULT: CONSISTENT — no differences")
        else:
            print(f"\n  RESULT: INCONSISTENT")
            print(f"    Row difference:  {row_diff}")
            print(f"    Hour difference: {hour_diff:,.2f}")


def main():
    settings = load_settings()
    if not settings.is_configured():
        print("Not configured. Run: python src/main.py --setup")
        sys.exit(1)

    client_key = "LSC"
    try:
        master = MasterConfig()
        client_config = master.get_client(client_key)
    except (FileNotFoundError, KeyError) as e:
        print(f"Error loading master config for client '{client_key}': {e}")
        sys.exit(1)

    hive_cfg = client_config.hive
    if not hive_cfg.workspace_id or not hive_cfg.user_id:
        print(f"Hive workspace_id/user_id not found in master config for '{client_key}'.")
        sys.exit(1)

    hive = HiveService(
        HiveCredentials(
            api_key=settings.hive_api_key,
            user_id=hive_cfg.user_id,
            workspace_id=hive_cfg.workspace_id,
        )
    )

    print(f"Endpoint: {HIVE_GRAPHQL_URL}")
    print(f"Query:    getTimesheetReportingCsvExportData")
    print(f"Date:     {date.today()}")
    print(f"Testing Hive connection...")

    if not hive.test_connection():
        print("Failed to connect to Hive API")
        sys.exit(1)
    print("Connected.\n")

    all_stats = {}

    # ---- Test 1: 2025 Full Year ----
    print(f"{'#' * 60}")
    print(f"#  TEST 1: 2025 Full Year (Jan 1 – Dec 31)")
    print(f"{'#' * 60}")

    start_2025 = date(2025, 1, 1)
    end_2025 = date(2025, 12, 31)

    print(f"\n  Fetching {start_2025} to {end_2025}...")
    csv_2025 = hive.get_timesheet_report_csv_raw(start_2025, end_2025)
    filepath = save_csv(f"test_api_2025_{date.today()}.csv", csv_2025)
    print(f"  Saved to: {filepath}")
    stats = analyze_csv(csv_2025, "2025 Full Year")
    all_stats["2025"] = stats

    # ---- Test 2: 2026 YTD ----
    print(f"\n{'#' * 60}")
    print(f"#  TEST 2: 2026 Year-to-Date (Jan 1 – {date.today()})")
    print(f"{'#' * 60}")

    start_2026 = date(2026, 1, 1)
    end_2026 = date.today()

    print(f"\n  Fetching {start_2026} to {end_2026}...")
    csv_2026 = hive.get_timesheet_report_csv_raw(start_2026, end_2026)
    filepath = save_csv(f"test_api_2026_{date.today()}.csv", csv_2026)
    print(f"  Saved to: {filepath}")
    stats = analyze_csv(csv_2026, f"2026 YTD (through {end_2026})")
    all_stats["2026"] = stats

    # ---- Test 3: Consistency test ----
    run_consistency_test(hive)

    # ---- Reference values from original bug report ----
    print(f"\n{'#' * 60}")
    print(f"#  REFERENCE: Original bug report values (Feb 2026)")
    print(f"{'#' * 60}")
    print(f"\n  2025 Full Year (Jan 1 – Dec 31):")
    print(f"    Web UI:  4,103 rows / 9,812.62 hours")
    print(f"    Old API: 4,094 rows / 9,690.69 hours (9 rows missing, 121.93 hrs short)")
    if all_stats.get("2025"):
        s = all_stats["2025"]
        print(f"    NEW API: {s['rows']:,} rows / {s['total_hours']:,.2f} hours")
        row_vs_ui = s["rows"] - 4103
        hrs_vs_ui = round(s["total_hours"] - 9812.62, 2)
        print(f"    vs Web UI: {row_vs_ui:+d} rows / {hrs_vs_ui:+,.2f} hours")

    print(f"\n  2026 YTD (Jan 1 – Feb 16, from bug report):")
    print(f"    Web UI:  631 rows / 1,133.80 hours")
    print(f"    Old API: 631 rows / 1,126.98 hours (6.82 hrs short)")
    print(f"    (Note: today's 2026 pull covers a wider date range, so direct comparison not possible)")

    print(f"\n{'=' * 60}")
    print(f"  NEXT STEP: Download a fresh CSV from the Hive web UI for the")
    print(f"  same date ranges and compare row counts + total hours.")
    print(f"  CSV files saved in: {OUTPUT_DIR}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
