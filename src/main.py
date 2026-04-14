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

from config import (
    EXTRACTS, YEAR_EXTRACTS, OUTPUT_DIR, TABS, YEAR_TABS, CHECKS_TAB,
    COLUMN_ORDER, EXCLUDED_COLUMNS,
)
from settings import (
    AppSettings,
    load_settings,
    save_settings,
    ensure_config_dir,
    SHARED_CONFIG_DIR,
)
from logger_setup import setup_logger, get_logger
from services.hive_service import HiveService, HiveCredentials
from services.sheets_service import SheetsService
from notification import send_chat_notification
from gui.date_picker import select_date_range

# Add shared config to path so we can import config_reader
sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig, ClientConfig


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

    # Step 1: Hive API Key (the only secret stored locally)
    print("-" * 40)
    print("Step 1: Hive API Key")
    print("-" * 40)
    print("\nTo get your Hive API key:")
    print("  1. Log into Hive at https://app.hive.com")
    print("  2. Click your profile icon (bottom left)")
    print("  3. Go to 'Apps & Integrations' -> 'API'")
    print("  4. Generate a new API key (copy it immediately - shown only once)\n")
    print("Note: workspace_id and user_id are now managed in the Master Config sheet.")
    print("Only the API key (a secret) is stored locally.\n")

    api_key = input("Enter your Hive API key: ").strip()
    if not api_key:
        print("Error: API key is required")
        return False

    # Test Hive connection (basic auth check only - no workspace needed)
    print("\nTesting Hive API connection...")
    hive = HiveService(HiveCredentials(api_key=api_key, user_id="test"))
    if not hive.test_connection():
        print("Error: Failed to connect to Hive API. Please check your API key.")
        return False
    print("Successfully connected to Hive!")

    # Save settings (API key only)
    settings = AppSettings(hive_api_key=api_key)
    save_settings(settings)

    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"\nAPI key saved to OS keyring (Service: BosOpt, Username: Hive-APIKey)")
    print(f"Other settings saved to: {config_dir / 'settings.json'}")
    print(f"Excel files will be saved to: {OUTPUT_DIR}")
    print("\nOther settings (workspace_id, user_id, sheet IDs, webhooks)")
    print("are managed in the Master Config Google Sheet.")
    print("\nRun the extract with: python src/main.py [--client LSC]")

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


def _order_data(extract_key: str, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reorder dict keys to match the required column order for this extract.

    Required columns come first in the defined order, then any extra
    columns from the API are appended alphabetically.
    Columns in EXCLUDED_COLUMNS are always dropped.
    """
    required_order = COLUMN_ORDER.get(extract_key)
    if not required_order:
        return data

    # Collect all keys across all rows, minus excluded
    all_keys = set()
    for row in data:
        all_keys.update(row.keys())
    all_keys -= EXCLUDED_COLUMNS

    # Build final column list: required order first, then extras
    ordered = [c for c in required_order if c in all_keys]
    extras = sorted(all_keys - set(required_order))
    final_order = ordered + extras

    # Rewrite each row with the correct key order
    return [{col: row.get(col, "") for col in final_order} for row in data]


def _parse_numeric(value: str) -> float:
    """Parse a numeric string from a sheet cell, handling $, commas, and blanks."""
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "").replace("$", ""))
    except ValueError:
        return 0.0


def _sum_column(data: List[Dict[str, Any]], col_name: str) -> float:
    """Sum a numeric column across all rows in the data."""
    total = 0.0
    for row in data:
        val = row.get(col_name)
        if val is None or val == "":
            continue
        if isinstance(val, (int, float)):
            total += val
        elif isinstance(val, str):
            total += _parse_numeric(val)
    return total


def pre_write_project_check(
    sheets: SheetsService,
    active_data: List[Dict[str, Any]],
    archived_data: List[Dict[str, Any]],
) -> bool:
    """Sanity-check before overwriting BillingProject sheets.

    Reads the previous row counts (B2) and combined Amount Awarded total
    (N2 from BillingProject_RAW, which sums both sheets) before any data
    is cleared.  Compares against the new combined data.

    Row counts and total awarded should always be >= previous values
    (projects are added, never deleted).

    Returns True if safe to proceed, False if something looks wrong.
    A failure logs a WARNING but does NOT block the write.
    """
    logger = get_logger()

    tab_active = TABS["active_projects"]["name"]
    tab_archive = TABS["archived_projects"]["name"]

    # Read previous values before we touch anything
    prev_active_rows = _parse_numeric(sheets.read_cell(tab_active, "B2"))
    prev_archive_rows = _parse_numeric(sheets.read_cell(tab_archive, "B2"))
    # N1 on each sheet = awarded total for that sheet only
    prev_active_awarded = _parse_numeric(sheets.read_cell(tab_active, "N1"))
    prev_archive_awarded = _parse_numeric(sheets.read_cell(tab_archive, "N1"))

    prev_total_rows = prev_active_rows + prev_archive_rows
    prev_total_awarded = prev_active_awarded + prev_archive_awarded

    # Calculate new totals
    new_active_rows = len(active_data)
    new_archive_rows = len(archived_data)
    new_total_rows = new_active_rows + new_archive_rows
    new_active_awarded = _sum_column(active_data, "Amount Awarded")
    new_archive_awarded = _sum_column(archived_data, "Amount Awarded")
    new_total_awarded = new_active_awarded + new_archive_awarded

    logger.info(
        f"Pre-write check — previous: {prev_total_rows:.0f} rows "
        f"({prev_active_rows:.0f} active + {prev_archive_rows:.0f} archive), "
        f"${prev_total_awarded:,.2f} awarded"
    )
    logger.info(
        f"Pre-write check — new: {new_total_rows} rows "
        f"({new_active_rows} active + {new_archive_rows} archive), "
        f"${new_total_awarded:,.2f} awarded"
    )

    ok = True
    if new_total_rows < prev_total_rows:
        logger.warning(
            f"PRE-WRITE CHECK: Combined row count DROPPED from "
            f"{prev_total_rows:.0f} to {new_total_rows}"
        )
        ok = False
    if prev_total_awarded > 0 and new_total_awarded < prev_total_awarded:
        logger.warning(
            f"PRE-WRITE CHECK: Combined Amount Awarded DROPPED from "
            f"${prev_total_awarded:,.2f} to ${new_total_awarded:,.2f}"
        )
        ok = False

    if ok:
        logger.info("Pre-write check PASSED")

    return ok


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

    # Enforce column order
    data = _order_data(extract_key, data)

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

    if success:
        sheets.update_timestamp(tab_name, cell="C1")

    return rows if success else 0


def process_extract(
    hive: HiveService,
    extract_key: str,
    extract_config: dict,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    sheets: Optional[SheetsService] = None,
    write_excel: bool = False,
    prefetched_data: Optional[List[Dict[str, Any]]] = None,
) -> Dict:
    """
    Process a single extract — fetch data from Hive, write to Excel and Sheets.

    Args:
        prefetched_data: If provided, skip the Hive API call and use this data.

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
        # Use prefetched data or fetch from Hive
        data: List[Dict[str, Any]] = prefetched_data if prefetched_data is not None else []

        if prefetched_data is not None:
            pass  # already have the data
        elif extract_key == "active_projects":
            data = hive.get_projects(archived=False)
        elif extract_key == "archived_projects":
            data = hive.get_projects(archived=True)
        elif extract_key == "all_projects":
            data = hive.get_all_projects()
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


def run_extracts(
    from_date: date,
    to_date: date,
    client_config: ClientConfig,
    mode: str = "all",
    use_sheets: bool = True,
    use_excel: bool = False,
) -> int:
    """
    Run extracts based on mode.

    Modes:
        all        — Projects + MonthExact (supported extracts)
        projects   — Active, Archived, and combined Projects_ALL
        monthexact — Time tracking entries (MonthEXACT_RAW)
        timesheet  — Month_RAW, Year_RAW (NOT YET SUPPORTED - Hive API issue)
        yearly     — ALL_2020..ALL_2026 (NOT YET SUPPORTED - Hive API issue)

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger = get_logger()
    logger.info(f"Starting HIVE Extract (mode={mode}): {from_date} to {to_date}")
    run_start = time.time()

    # Validate mode
    SUPPORTED_MODES = {"all", "projects", "monthexact"}
    UNSUPPORTED_MODES = {"timesheet", "yearly"}
    valid_modes = SUPPORTED_MODES | UNSUPPORTED_MODES

    if mode not in valid_modes:
        logger.error(
            f"Unknown mode: {mode!r}. "
            f"Valid modes: {', '.join(sorted(valid_modes))}"
        )
        return 1

    if mode in UNSUPPORTED_MODES:
        logger.error(
            f"Mode {mode!r} is not yet supported — waiting for Hive API fix. "
            f"Supported modes: {', '.join(sorted(SUPPORTED_MODES))}"
        )
        return 1

    # Load local settings (API key only)
    settings = load_settings()
    if not settings.is_configured():
        logger.error("Hive API key not configured. Run with --setup first.")
        return 1

    # Get Hive config from MasterConfig
    hive_cfg = client_config.hive
    if not hive_cfg.workspace_id or not hive_cfg.user_id:
        logger.error(
            f"Hive workspace_id/user_id not found in master config for this client. "
            f"Check the Hive tab in the Master Config sheet."
        )
        return 1

    # Initialize Hive service — API key from local secrets, IDs from master config
    hive = HiveService(
        HiveCredentials(
            api_key=settings.hive_api_key,
            user_id=hive_cfg.user_id,
            workspace_id=hive_cfg.workspace_id,
        )
    )

    # Test connection
    logger.info("Connecting to Hive...")
    if not hive.test_connection():
        logger.error("Failed to connect to Hive API")
        return 1

    # Initialize Google Sheets service if requested
    sheets: Optional[SheetsService] = None
    spreadsheet_id = client_config.sheets.hive_extract_sheet_id
    credential_ref = client_config.client.google_auth_override or "BosOpt"

    if use_sheets:
        if not spreadsheet_id:
            logger.error(
                "hive_extract_sheet_id not found in master config. "
                "Add it to the Sheets tab in the Master Config sheet, "
                "or use --no-sheets to skip Sheets output."
            )
            return 1
        else:
            sheets = SheetsService(spreadsheet_id, credential_ref=credential_ref)
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

    run_projects = mode in ("all", "projects")
    run_monthexact = mode in ("all", "monthexact")

    # 1. Projects (active, archived, combined)
    if run_projects:
        # Fetch active and archived data first (before any writes)
        logger.info("Fetching project data from Hive...")
        active_data = hive.get_projects(archived=False)
        archived_data = hive.get_projects(archived=True)

        # Pre-write sanity check: compare new totals against existing sheet data
        if sheets:
            pre_write_project_check(sheets, active_data, archived_data)

        # Now process each extract using the prefetched data
        for key, data in [
            ("active_projects", active_data),
            ("archived_projects", archived_data),
            ("all_projects", active_data + archived_data),
        ]:
            config = EXTRACTS[key]
            result = process_extract(
                hive, key, config, from_date, to_date, sheets, use_excel,
                prefetched_data=data,
            )
            results[config["filename"]] = result

    # 2. MonthEXACT (time tracking entries)
    if run_monthexact:
        config = EXTRACTS["time_tracking"]
        result = process_extract(hive, "time_tracking", config, from_date, to_date, sheets, use_excel)
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

    # --- Checks validation (delay to let Sheets recalculate after bulk writes) ---
    checks_value = ""
    checks_ok = False
    checks_location = f"{CHECKS_TAB['name']}!{CHECKS_TAB['cell']}"
    if sheets:
        time.sleep(30)
        try:
            checks_value = sheets.read_cell(CHECKS_TAB["name"], CHECKS_TAB["cell"]).strip()
        except Exception:
            checks_value = f"N/A (could not read {checks_location})"
        checks_ok = checks_value.upper() == "ALL GOOD"
        if checks_ok:
            logger.info("Checks validation: ALL GOOD")
        else:
            logger.warning(f"Checks validation: PROBLEMS DETECTED — {checks_value!r} (see {checks_location})")

    # --- Google Chat notification ---
    notification_msg = f"HIVE Extract complete ({total_elapsed:.1f}s)\n"
    for name, r in results.items():
        status = r["status"]
        rows = r.get("rows", 0)
        if status == "success":
            notification_msg += f"  ✓ {name}: {rows} rows\n"
        elif status == "error":
            notification_msg += f"  ✗ {name}: ERROR - {r.get('error', '')}\n"
        else:
            notification_msg += f"  − {name}: skipped\n"
    if sheets:
        if checks_ok:
            notification_msg += "Checks: ALL GOOD"
        else:
            notification_msg += f"Checks: PROBLEMS DETECTED — {checks_value}"
    else:
        notification_msg += "Checks: skipped (Sheets not connected)"

    webhook_url = client_config.notifications.google_chat_webhook
    if webhook_url:
        send_chat_notification(webhook_url, notification_msg)
    else:
        logger.debug("Google Chat webhook not configured, skipping notification")

    # Build structured result for JSON output
    result_dict = {
        "status": "success" if error_count == 0 else "partial",
        "results": {k: {
            "description": v.get("description", k),
            "status": v["status"],
            "rows": v.get("rows", 0),
            "time": round(v.get("time", 0), 1),
            "error": v.get("error"),
        } for k, v in results.items()},
        "checks": checks_value if not checks_ok else "ALL GOOD",
        "checks_ok": checks_ok,
        "checks_location": checks_location if not checks_ok else "",
        "total_rows": total_rows,
        "success_count": success_count,
        "error_count": error_count,
        "elapsed": round(total_elapsed, 1),
        "mode": mode,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
    }

    return result_dict


def main():
    """Main entry point."""
    from datetime import timedelta

    parser = argparse.ArgumentParser(
        description="HIVE Extract - Export Hive data to Excel and Google Sheets"
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="all",
        choices=["all", "projects", "monthexact", "timesheet", "yearly"],
        help=(
            "What to extract: "
            "all (Projects + MonthExact), "
            "projects (Active/Archived/Combined), "
            "monthexact (time tracking entries), "
            "timesheet (NOT YET SUPPORTED), "
            "yearly (NOT YET SUPPORTED). "
            "Default: all"
        ),
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the setup wizard",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        help="Start date (YYYY-MM-DD) - default: today minus 45 days",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        help="End date (YYYY-MM-DD) - default: today",
    )
    parser.add_argument(
        "--client",
        type=str,
        default="LSC",
        help="Client key in MasterConfig (default: LSC)",
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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON result to stdout (for portal/scheduler integration)",
    )

    args = parser.parse_args()

    # Set up logging
    logger = setup_logger()

    # Run setup if requested
    if args.setup:
        success = run_setup()
        sys.exit(0 if success else 1)

    # Check if API key is in the OS keyring
    settings = load_settings()
    if not settings.is_configured():
        print("Hive API key not found in OS keyring (Service: BosOpt, Username: Hive-APIKey).")
        print("Run with --setup to configure, or add it manually via:")
        print("  python -c \"import keyring; keyring.set_password('BosOpt', 'Hive-APIKey', 'YOUR_KEY')\"")
        sys.exit(1)

    # Load master config for the specified client
    client_key = args.client
    logger.info(f"Loading master config for client: {client_key}")
    try:
        master = MasterConfig()
        client_config = master.get_client(client_key)
    except (FileNotFoundError, KeyError) as e:
        print(f"Error loading master config for client '{client_key}': {e}")
        sys.exit(1)

    logger.info(
        f"Client: {client_key}, "
        f"google_auth={client_config.client.google_auth_override or 'BosOpt'}, "
        f"hive_extract_sheet_id={client_config.sheets.hive_extract_sheet_id}"
    )

    # Date range — default: today-45 days through today
    to_date = date.today()
    from_date = to_date - timedelta(days=45)

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

    mode = args.mode
    print(f"Client: {client_key}")
    print(f"Mode: {mode}")
    print(f"Date range: {from_date} to {to_date}")

    # Run extracts
    use_sheets = not args.no_sheets
    use_excel = args.excel
    result = run_extracts(
        from_date, to_date, client_config,
        mode=mode, use_sheets=use_sheets, use_excel=use_excel,
    )

    # Output JSON for portal/scheduler integration
    if args.json:
        import json as _json
        print("---JSON_RESULT---")
        print(_json.dumps(result))

    sys.exit(0 if result["error_count"] == 0 else 1)


if __name__ == "__main__":
    main()
