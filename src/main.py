"""Main entry point for HIVE_Extract — pulls Hive data into Excel files."""

import calendar
import csv
import io
import sys
import argparse
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Any, Optional

import re

from openpyxl import Workbook

from config import EXTRACTS, YEAR_EXTRACTS, OUTPUT_DIR, TABS, YEAR_TABS
from settings import (
    AppSettings,
    load_settings,
    save_settings,
    ensure_config_dir,
)
from logger_setup import setup_logger, get_logger
from services.hive_service import HiveService, HiveCredentials
from services.sheets_service import SheetsService
from gui.date_picker import select_date_range


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _typed_value(val):
    """Convert a value to a native Python type so Excel stores it properly.

    - date strings  (YYYY-MM-DD)  → datetime.date
    - integer strings              → int
    - decimal strings              → float
    - percentages like "1.39%"     → float  (as 0.0139 so Excel % format works)
    - None / list / dict           → safe string
    - everything else              → unchanged
    """
    if val is None:
        return ""
    if isinstance(val, (int, float, date)):
        return val
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v) if val else ""
    if isinstance(val, dict):
        return str(val)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return ""
        # Date: YYYY-MM-DD
        if _DATE_RE.match(s):
            try:
                return date.fromisoformat(s)
            except ValueError:
                pass
        # Percentage: "1.39%"
        if s.endswith("%"):
            try:
                return float(s[:-1]) / 100.0
            except ValueError:
                pass
        # Number (allow commas as thousands separators, e.g. "221,500")
        stripped = s.replace(",", "")
        try:
            return int(stripped)
        except ValueError:
            pass
        try:
            return float(stripped)
        except ValueError:
            pass
    return val


def write_excel_file(filepath: Path, data: List[Dict[str, Any]]) -> int:
    """
    Write a list of dicts to an Excel file.

    Returns:
        Number of rows written
    """
    if not data:
        return 0

    wb = Workbook()
    ws = wb.active

    # Collect all unique headers across ALL rows, preserving first-seen order.
    seen = set()
    headers = []
    for row in data:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                headers.append(key)

    ws.append(headers)

    for row in data:
        ws.append([_typed_value(row.get(h, "")) for h in headers])

    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(filepath))
    return len(data)


def write_excel_from_csv(
    filepath: Path,
    csv_string: str,
    from_date: date,
    to_date: date,
) -> int:
    """
    Parse a raw CSV string from Hive, filter rows to the date range,
    and write to an Excel file.

    Returns:
        Number of data rows written
    """
    if not csv_string:
        return 0

    reader = csv.DictReader(io.StringIO(csv_string))
    fieldnames = reader.fieldnames or []

    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    wb = Workbook()
    ws = wb.active
    ws.append(fieldnames)

    count = 0
    for row in reader:
        row_date = row.get("Date", "")
        # Skip rows outside the date range (Hive API returns extras)
        if row_date and not (from_str <= row_date <= to_str):
            continue
        # Skip malformed rows (broken multi-line values with no Date)
        if not row_date:
            continue
        ws.append([_typed_value(row.get(h, "")) for h in fieldnames])
        count += 1

    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(filepath))
    return count


def run_setup() -> bool:
    """
    Run the setup wizard to configure the application.

    Returns:
        True if setup completed successfully, False otherwise
    """
    print("\n" + "=" * 60)
    print("HIVE Extract - Setup Wizard")
    print("=" * 60 + "\n")

    config_dir = ensure_config_dir()
    print(f"Config directory: {config_dir}\n")

    # Step 1: Hive API Credentials
    print("-" * 40)
    print("Step 1: Hive API Credentials")
    print("-" * 40)
    print("\nTo get your Hive API credentials:")
    print("  1. Log into Hive at https://app.hive.com")
    print("  2. Click your profile icon (bottom left)")
    print("  3. Go to 'Apps & Integrations' -> 'API'")
    print("  4. Generate a new API key (copy it immediately - shown only once)")
    print("  5. Note your User ID from the same page\n")

    api_key = input("Enter your Hive API key: ").strip()
    if not api_key:
        print("Error: API key is required")
        return False

    user_id = input("Enter your Hive User ID: ").strip()
    if not user_id:
        print("Error: User ID is required")
        return False

    # Test Hive connection
    print("\nTesting Hive API connection...")
    hive = HiveService(HiveCredentials(api_key=api_key, user_id=user_id))
    if not hive.test_connection():
        print("Error: Failed to connect to Hive API. Please check your credentials.")
        return False
    print("Successfully connected to Hive!")

    # Step 2: Workspace Selection
    print("\nFetching available workspaces...")
    workspaces = hive.get_workspaces()

    if not workspaces:
        print("Error: No workspaces found. Please check your credentials.")
        return False

    workspace_id = ""
    if len(workspaces) == 1:
        ws = workspaces[0]
        workspace_id = ws.get("id", "")
        ws_name = ws.get("name", "Unknown")
        print(f"Auto-selected workspace: {ws_name} (ID: {workspace_id})")
    else:
        print(f"\nFound {len(workspaces)} workspaces:")
        for i, ws in enumerate(workspaces, 1):
            print(f"  {i}. {ws.get('name', 'Unknown')} (ID: {ws.get('id', '')})")

        while True:
            choice = input(f"\nSelect workspace [1-{len(workspaces)}]: ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(workspaces):
                    workspace_id = workspaces[idx].get("id", "")
                    break
                print(f"Please enter a number between 1 and {len(workspaces)}")
            except ValueError:
                print("Please enter a valid number")

    if not workspace_id:
        print("Error: Could not determine workspace ID")
        return False

    print(f"Workspace ID: {workspace_id}")

    # Save settings
    settings = AppSettings(
        hive_api_key=api_key,
        hive_user_id=user_id,
        hive_workspace_id=workspace_id,
    )
    save_settings(settings)

    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"\nSettings saved to: {config_dir / 'settings.json'}")
    print(f"Excel files will be saved to: {OUTPUT_DIR}")
    print("\nRun the extract with: python src/main.py")

    return True


def parse_csv_to_dicts(
    csv_string: str,
    from_date: date,
    to_date: date,
) -> List[Dict[str, Any]]:
    """Parse raw CSV string, filter by date range, return list of dicts."""
    if not csv_string:
        return []

    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    reader = csv.DictReader(io.StringIO(csv_string))
    rows = []
    for row in reader:
        row_date = row.get("Date", "")
        if row_date and not (from_str <= row_date <= to_str):
            continue
        if not row_date:
            continue
        rows.append(row)
    return rows


def write_to_sheets(
    sheets: SheetsService,
    extract_key: str,
    data: List[Dict[str, Any]],
) -> int:
    """Write data to the appropriate Google Sheets tab.

    Rows 1-3 are reserved for formulas and never touched.
    Headers go in row 4, data starts in row 5.
    """
    if not data:
        return 0

    # Get tab config
    tab_config = TABS.get(extract_key) or YEAR_TABS.get(extract_key)
    if not tab_config:
        return 0

    tab_name = tab_config["name"]
    header_row = tab_config["header_row"]  # Row 4
    data_start_row = tab_config["data_start_row"]  # Row 5

    # Clear existing data (from row 4 onward - headers + data)
    sheets.clear_tab_data(tab_name, header_row)

    # Write headers and data
    success, rows = sheets.write_data(
        tab_name=tab_name,
        data=data,
        data_start_row=data_start_row,
        include_headers=True,
        header_row=header_row,
    )
    return rows if success else 0


def process_extract(
    hive: HiveService,
    extract_key: str,
    extract_config: dict,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    sheets: Optional[SheetsService] = None,
    write_excel: bool = False,
) -> Dict:
    """
    Process a single extract — fetch data from Hive, write to Excel and Sheets.

    Returns:
        Result dict with status, rows, and any error
    """
    logger = get_logger()
    filename = extract_config["filename"]
    description = extract_config["description"]
    filepath = OUTPUT_DIR / filename

    logger.info(f"Processing: {description} -> {filename}")

    t0 = time.time()
    try:
        # Fetch data based on extract type
        data: List[Dict[str, Any]] = []

        if extract_key == "active_projects":
            data = hive.get_projects(archived=False)
        elif extract_key == "archived_projects":
            data = hive.get_projects(archived=True)
        elif extract_key == "time_tracking":
            if not from_date or not to_date:
                raise ValueError("Date range required for time tracking")
            data = hive.get_time_entries(from_date, to_date)
        elif extract_key == "month_raw":
            today = date.today()
            month_start = date(today.year, today.month, 1)
            csv_string = hive.get_timesheet_report_csv_raw(month_start, today)
            data = parse_csv_to_dicts(csv_string, month_start, today)
        elif extract_key == "year_raw":
            today = date.today()
            year_start = date(today.year, 1, 1)
            csv_string = hive.get_timesheet_report_csv_raw(year_start, today)
            data = parse_csv_to_dicts(csv_string, year_start, today)
        elif extract_key.startswith("ALL_"):
            year = int(extract_key.split("_")[1])
            csv_string = hive.get_year_timesheet_report_raw(year)
            yr_start = date(year, 1, 1)
            today = date.today()
            yr_end = date(year, 12, 31) if year < today.year else today
            data = parse_csv_to_dicts(csv_string, yr_start, yr_end)
        else:
            raise ValueError(f"Unknown extract type: {extract_key}")

        rows = len(data)

        # Write to Google Sheets if connected
        if sheets:
            sheet_rows = write_to_sheets(sheets, extract_key, data)
            logger.info(f"Wrote {sheet_rows} rows to Google Sheets tab")
            rows = sheet_rows

        # Write to Excel if requested
        if write_excel:
            excel_rows = write_excel_file(filepath, data)
            logger.info(f"Wrote {excel_rows} rows to {filename}")
            if not sheets:
                rows = excel_rows

        elapsed = time.time() - t0
        logger.info(f"Processed {rows} rows ({elapsed:.1f}s)")
        return {"status": "success", "rows": rows, "time": elapsed}

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"Error processing {description}: {e} ({elapsed:.1f}s)")
        return {"status": "error", "rows": 0, "error": str(e), "time": elapsed}


def run_extracts(from_date: date, to_date: date, use_sheets: bool = True, use_excel: bool = False) -> int:
    """
    Run all extracts.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger = get_logger()
    logger.info(f"Starting HIVE Extract: {from_date} to {to_date}")
    run_start = time.time()

    # Load settings
    settings = load_settings()
    if not settings.is_configured():
        logger.error("Application not configured. Run with --setup first.")
        return 1

    # Initialize Hive service
    hive = HiveService(
        HiveCredentials(
            api_key=settings.hive_api_key,
            user_id=settings.hive_user_id,
            workspace_id=settings.hive_workspace_id,
        )
    )

    # Test connection
    logger.info("Connecting to Hive...")
    if not hive.test_connection():
        logger.error("Failed to connect to Hive API")
        return 1

    # Initialize Google Sheets service if requested
    sheets: Optional[SheetsService] = None
    if use_sheets:
        from config import SPREADSHEET_ID
        sheets = SheetsService(SPREADSHEET_ID)
        if sheets.authenticate():
            if not sheets.test_access():
                logger.warning("Could not access Google Sheet, continuing without Sheets")
                sheets = None
        else:
            logger.warning("Google Sheets auth failed, continuing without Sheets")
            sheets = None

    # Ensure output directory exists if writing Excel
    if use_excel:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Track results
    results: Dict[str, dict] = {}

    # Process standard extracts
    for key, config in EXTRACTS.items():
        result = process_extract(hive, key, config, from_date, to_date, sheets, use_excel)
        results[config["filename"]] = result

    # Process year extracts
    current_year = date.today().year
    for key, config in YEAR_EXTRACTS.items():
        year = int(key.split("_")[1])
        if year > current_year:
            results[config["filename"]] = {
                "status": "skipped",
                "rows": 0,
                "error": "Future year",
            }
            continue

        result = process_extract(hive, key, config, sheets=sheets, write_excel=use_excel)
        results[config["filename"]] = result

    # Log summary
    success_count = sum(1 for r in results.values() if r["status"] == "success")
    error_count = sum(1 for r in results.values() if r["status"] == "error")
    skipped_count = sum(1 for r in results.values() if r["status"] == "skipped")

    total_elapsed = time.time() - run_start

    output_modes = []
    if sheets:
        output_modes.append("Google Sheets")
    if use_excel:
        output_modes.append("Excel")
    output_status = " + ".join(output_modes) if output_modes else "No output"

    logger.info(
        f"Extract complete ({output_status}): {success_count} succeeded, {error_count} failed, "
        f"{skipped_count} skipped in {total_elapsed:.1f}s"
    )

    print(f"\nOutput: {output_status}")
    if use_excel:
        print(f"Excel files: {OUTPUT_DIR}")
    for name, r in results.items():
        status = r["status"]
        rows = r.get("rows", 0)
        t = r.get("time", 0)
        if status == "success":
            print(f"  {name}: {rows} rows ({t:.1f}s)")
        elif status == "error":
            print(f"  {name}: ERROR - {r.get('error', '')} ({t:.1f}s)")
        else:
            print(f"  {name}: skipped")

    total_rows = sum(r.get("rows", 0) for r in results.values())
    print(f"\n  Total: {total_rows} rows, {total_elapsed:.1f}s elapsed")

    return 0 if error_count == 0 else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="HIVE Extract - Export Hive data to Excel and Google Sheets"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the setup wizard",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        help="Start date (YYYY-MM-DD) - default: earlier of Jan 1 or 2 months ago",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        help="End date (YYYY-MM-DD) - default: today",
    )
    parser.add_argument(
        "--no-sheets",
        action="store_true",
        help="Skip Google Sheets output",
    )
    parser.add_argument(
        "--excel",
        action="store_true",
        help="Also write Excel files locally (default: Sheets only)",
    )

    args = parser.parse_args()

    # Set up logging
    logger = setup_logger()

    # Run setup if requested
    if args.setup:
        success = run_setup()
        sys.exit(0 if success else 1)

    # Check if settings exist
    settings = load_settings()
    if not settings.is_configured():
        print("Application not configured. Run with --setup first:")
        print("  python src/main.py --setup")
        sys.exit(1)

    # Get date range — defaults: today and the earlier of Jan 1 or 2 months ago
    to_date = date.today()
    m = to_date.month - 2
    y = to_date.year
    if m <= 0:
        m += 12
        y -= 1
    max_day = calendar.monthrange(y, m)[1]
    two_months_ago = date(y, m, min(to_date.day, max_day))
    jan1 = date(to_date.year, 1, 1)
    from_date = min(jan1, two_months_ago)

    if args.from_date:
        try:
            from_date = date.fromisoformat(args.from_date)
        except ValueError as e:
            print(f"Invalid from-date: {e}  (use YYYY-MM-DD)")
            sys.exit(1)
    if args.to_date:
        try:
            to_date = date.fromisoformat(args.to_date)
        except ValueError as e:
            print(f"Invalid to-date: {e}  (use YYYY-MM-DD)")
            sys.exit(1)

    # Show date range being used
    print(f"MonthEXACT date range: {from_date} to {to_date}")

    # Run extracts
    use_sheets = not args.no_sheets
    use_excel = args.excel
    exit_code = run_extracts(from_date, to_date, use_sheets=use_sheets, use_excel=use_excel)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
