"""Compare Hive API data vs current Google Sheets data (read-only test).

Uses key-based matching (not positional) to avoid false diffs from sort order.
"""

import sys
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).parent))

from config import TABS
from settings import load_settings, SHARED_CONFIG_DIR
from logger_setup import setup_logger, get_logger
from services.hive_service import HiveService, HiveCredentials
from services.sheets_service import SheetsService

# Add shared config to path so we can import config_reader
sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


def read_sheet_tab(sheets: SheetsService, tab_name: str, header_row: int, data_start_row: int) -> List[Dict[str, str]]:
    """Read all data from a Google Sheets tab and return as list of dicts."""
    headers = sheets.get_tab_headers(tab_name, header_row)
    if not headers:
        return []

    range_name = f"'{tab_name}'!A{data_start_row}:ZZ"
    result = (
        sheets.sheets.spreadsheets()
        .values()
        .get(spreadsheetId=sheets.spreadsheet_id, range=range_name)
        .execute()
    )
    raw_rows = result.get("values", [])

    rows = []
    for raw in raw_rows:
        row = {}
        for i, h in enumerate(headers):
            row[h] = raw[i] if i < len(raw) else ""
        rows.append(row)
    return rows


def normalize(val: Any) -> str:
    """Normalize a value to a comparable string."""
    if val is None:
        return ""
    s = str(val).strip()
    # Remove trailing .0 from floats that are really ints
    if s.endswith(".0"):
        try:
            float(s)
            s = s[:-2]
        except ValueError:
            pass
    # Normalize zero representations
    if s in ("0:00", "0.0", "0.00"):
        s = "0"
    return s


def normalize_date(val: str) -> str:
    """Try to normalize various date formats to YYYY-MM-DD for comparison."""
    s = val.strip()
    if not s:
        return ""
    # Already ISO format
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return s
    # Try common Sheets formats
    import re
    from datetime import datetime
    for fmt in ("%d-%b-%y", "%b %d, %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def make_key_projects(row: Dict[str, Any]) -> str:
    """Create a matching key for project rows using Project ID."""
    pid = normalize(row.get("Project ID", ""))
    return pid


def make_key_time(row: Dict[str, Any]) -> str:
    """Create a matching key for time tracking rows.

    Combine multiple fields since there's no single unique ID.
    """
    parts = [
        normalize(row.get("Project", "")),
        normalize(row.get("Action Title", "")),
        normalize(row.get("Time Tracked By", "")),
        normalize(row.get("Time Tracked Date", "")),
        normalize(row.get("Tracked (Minutes)", "")),
        normalize(row.get("Description", ""))[:50],
    ]
    return "|".join(parts)


def index_by_key(data: List[Dict[str, Any]], key_fn) -> Dict[str, List[Dict[str, Any]]]:
    """Index rows by a key function. Multiple rows can share the same key."""
    idx = {}
    for row in data:
        k = key_fn(row)
        idx.setdefault(k, []).append(row)
    return idx


# Date-like column names for smarter comparison
DATE_COLUMNS = {
    "Start Date", "End Date", "Archived at", "Date Submitted",
    "Funder Notification Date", "Grant Period Start Date", "Grant Period End Date",
    "Time Tracked Date",
}


def compare_values(col: str, hive_val: str, sheet_val: str) -> bool:
    """Compare two normalized values, with date-aware logic."""
    if hive_val == sheet_val:
        return True
    # Try date normalization for date columns
    if col in DATE_COLUMNS:
        return normalize_date(hive_val) == normalize_date(sheet_val)
    return False


def compare_keyed(
    name: str,
    hive_data: List[Dict[str, Any]],
    sheet_data: List[Dict[str, str]],
    key_fn,
) -> Dict[str, Any]:
    """Compare datasets using key-based matching."""

    report = {
        "name": name,
        "hive_rows": len(hive_data),
        "sheet_rows": len(sheet_data),
    }

    # Headers
    hive_headers = set()
    for row in hive_data:
        hive_headers.update(row.keys())
    sheet_headers = set()
    for row in sheet_data:
        sheet_headers.update(row.keys())

    only_in_hive = sorted(hive_headers - sheet_headers)
    only_in_sheet = sorted(sheet_headers - hive_headers)
    common_headers = sorted(hive_headers & sheet_headers)

    # Index both sides
    hive_idx = index_by_key(hive_data, key_fn)
    sheet_idx = index_by_key(sheet_data, key_fn)

    hive_keys = set(hive_idx.keys())
    sheet_keys = set(sheet_idx.keys())

    only_in_hive_keys = hive_keys - sheet_keys
    only_in_sheet_keys = sheet_keys - hive_keys
    matched_keys = hive_keys & sheet_keys

    # For matched keys, compare values on common headers
    value_diffs = []
    max_diffs = 30
    total_value_diffs = 0

    for key in sorted(matched_keys):
        hive_rows = hive_idx[key]
        sheet_rows = sheet_idx[key]
        # Compare first occurrence
        h_row = hive_rows[0]
        s_row = sheet_rows[0]
        for col in common_headers:
            hv = normalize(h_row.get(col, ""))
            sv = normalize(s_row.get(col, ""))
            if not compare_values(col, hv, sv):
                total_value_diffs += 1
                if len(value_diffs) < max_diffs:
                    value_diffs.append({
                        "key": key[:40],
                        "column": col,
                        "hive": hv[:60],
                        "sheet": sv[:60],
                    })

    report["matched_keys"] = len(matched_keys)
    report["only_in_hive_count"] = len(only_in_hive_keys)
    report["only_in_sheet_count"] = len(only_in_sheet_keys)
    report["common_columns"] = len(common_headers)
    report["only_in_hive_cols"] = only_in_hive
    report["only_in_sheet_cols"] = only_in_sheet
    report["total_value_diffs"] = total_value_diffs
    report["value_diffs"] = value_diffs
    report["only_in_hive_keys_sample"] = sorted(only_in_hive_keys)[:15]
    report["only_in_sheet_keys_sample"] = sorted(only_in_sheet_keys)[:15]

    # Determine overall status
    if (len(only_in_hive_keys) == 0 and len(only_in_sheet_keys) == 0
            and total_value_diffs == 0 and not only_in_hive and not only_in_sheet):
        report["summary"] = "MATCH"
    else:
        parts = []
        if only_in_hive_keys:
            parts.append(f"{len(only_in_hive_keys)} rows only in Hive")
        if only_in_sheet_keys:
            parts.append(f"{len(only_in_sheet_keys)} rows only in Sheet")
        if total_value_diffs:
            parts.append(f"{total_value_diffs} value diffs in matched rows")
        if only_in_hive:
            parts.append(f"{len(only_in_hive)} columns only in Hive")
        if only_in_sheet:
            parts.append(f"{len(only_in_sheet)} columns only in Sheet")
        report["summary"] = "DIFFERENCES - " + "; ".join(parts)

    return report


def print_report(report: Dict[str, Any]):
    """Print a comparison report."""
    print(f"\n{'=' * 70}")
    print(f"  {report['name']}")
    print(f"{'=' * 70}")
    print(f"  Hive API rows:     {report['hive_rows']}")
    print(f"  Sheet rows:        {report['sheet_rows']}")
    print(f"  Matched by key:    {report['matched_keys']}")
    print(f"  Only in Hive:      {report['only_in_hive_count']} rows")
    print(f"  Only in Sheet:     {report['only_in_sheet_count']} rows")
    print(f"  Common columns:    {report['common_columns']}")
    print(f"  Value diffs:       {report['total_value_diffs']}")
    print(f"  Result:            {report['summary']}")

    if report["only_in_hive_cols"]:
        print(f"\n  Columns only in Hive API:")
        for c in report["only_in_hive_cols"]:
            print(f"    - {c}")

    if report["only_in_sheet_cols"]:
        print(f"\n  Columns only in Google Sheet:")
        for c in report["only_in_sheet_cols"]:
            print(f"    - {c}")

    if report["only_in_hive_keys_sample"]:
        print(f"\n  Sample rows only in Hive (by key):")
        for k in report["only_in_hive_keys_sample"]:
            print(f"    - {k}")

    if report["only_in_sheet_keys_sample"]:
        print(f"\n  Sample rows only in Sheet (by key):")
        for k in report["only_in_sheet_keys_sample"]:
            print(f"    - {k}")

    if report["value_diffs"]:
        print(f"\n  Value diffs (first {len(report['value_diffs'])} of {report['total_value_diffs']}):")
        print(f"    {'Key':<42} {'Column':<22} {'Hive':<25} {'Sheet':<25}")
        print(f"    {'-'*42} {'-'*22} {'-'*25} {'-'*25}")
        for d in report["value_diffs"]:
            print(f"    {d['key']:<42} {d['column']:<22} {d['hive']:<25} {d['sheet']:<25}")


def main():
    logger = setup_logger()
    logger.info("Starting Hive vs Google Sheets comparison test (key-based)")

    settings = load_settings()
    if not settings.is_configured():
        print("Not configured. Run: python src/main.py --setup")
        sys.exit(1)

    # Load master config (hardcoded to LSC for this test script)
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

    spreadsheet_id = client_config.sheets.hive_extract_sheet_id
    if not spreadsheet_id:
        print(f"hive_extract_sheet_id not found in master config for '{client_key}'.")
        sys.exit(1)

    credential_ref = client_config.client.google_auth_override or "BosOpt"

    hive = HiveService(
        HiveCredentials(
            api_key=settings.hive_api_key,
            user_id=hive_cfg.user_id,
            workspace_id=hive_cfg.workspace_id,
        )
    )

    print("Connecting to Hive API...")
    if not hive.test_connection():
        print("Failed to connect to Hive API")
        sys.exit(1)
    print("Hive API connected.")

    sheets = SheetsService(spreadsheet_id, credential_ref=credential_ref)
    print("Authenticating with Google Sheets...")
    if not sheets.authenticate():
        print("Failed to authenticate with Google Sheets")
        sys.exit(1)
    if not sheets.test_access():
        print("Failed to access spreadsheet")
        sys.exit(1)
    print("Google Sheets connected.")

    reports = []

    # --- 1. Active Projects (BillingProject_RAW) ---
    print("\n[1/3] Fetching Active Projects from Hive...")
    hive_active = hive.get_projects(archived=False)
    tab_cfg = TABS["active_projects"]
    print(f"       Fetched {len(hive_active)} rows from Hive")

    print("       Reading BillingProject_RAW from Google Sheets...")
    sheet_active = read_sheet_tab(sheets, tab_cfg["name"], tab_cfg["header_row"], tab_cfg["data_start_row"])
    print(f"       Read {len(sheet_active)} rows from Sheet")

    reports.append(compare_keyed("Active Projects (BillingProject_RAW)", hive_active, sheet_active, make_key_projects))

    # --- 2. Archived Projects (BillingProject_RAW_Archive) ---
    print("\n[2/3] Fetching Archived Projects from Hive...")
    hive_archived = hive.get_projects(archived=True)
    tab_cfg = TABS["archived_projects"]
    print(f"       Fetched {len(hive_archived)} rows from Hive")

    print("       Reading BillingProject_RAW_Archive from Google Sheets...")
    sheet_archived = read_sheet_tab(sheets, tab_cfg["name"], tab_cfg["header_row"], tab_cfg["data_start_row"])
    print(f"       Read {len(sheet_archived)} rows from Sheet")

    reports.append(compare_keyed("Archived Projects (BillingProject_RAW_Archive)", hive_archived, sheet_archived, make_key_projects))

    # --- 3. Time Tracking Jan 1 - Feb 26, 2026 (MonthEXACT_RAW) ---
    from_date = date(2026, 1, 1)
    to_date = date(2026, 2, 26)

    print(f"\n[3/3] Fetching Time Tracking ({from_date} to {to_date}) from Hive...")
    hive_time = hive.get_time_entries(from_date, to_date)
    tab_cfg = TABS["time_tracking"]
    print(f"       Fetched {len(hive_time)} rows from Hive")

    print("       Reading MonthEXACT_RAW from Google Sheets...")
    sheet_time = read_sheet_tab(sheets, tab_cfg["name"], tab_cfg["header_row"], tab_cfg["data_start_row"])
    print(f"       Read {len(sheet_time)} rows from Sheet")

    reports.append(compare_keyed("Time Tracking (MonthEXACT_RAW)", hive_time, sheet_time, make_key_time))

    # --- Print all reports ---
    print("\n" + "#" * 70)
    print("#  COMPARISON RESULTS (key-based matching)")
    print("#" * 70)

    for r in reports:
        print_report(r)

    # Overall summary
    print(f"\n{'=' * 70}")
    all_match = all(r["summary"] == "MATCH" for r in reports)
    if all_match:
        print("  OVERALL: ALL 3 EXTRACTS MATCH")
    else:
        print("  OVERALL: DIFFERENCES DETECTED")
        for r in reports:
            status = "MATCH" if r["summary"] == "MATCH" else "DIFF"
            print(f"    [{status}] {r['name']}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
