"""Enriched All + Month extract — runs the two-pass Hive query, aggregates
by Person + Project + Category + Month, enriches with project metadata,
writes to the canonical All tab layout (26 cols, Row 4 header).

Modes:
    --mode preview     → fetch + aggregate, write first 100 rows to
                          output/all_enriched_preview.json. No sheet write.
    --mode test        → fetch + aggregate, write to All_TEST tab only.
    --mode production  → fetch + aggregate, write to All + Month tabs.

Usage:
    ./venv-linux/bin/python src/run_all_extract.py --mode preview [--client LSC]
    ./venv-linux/bin/python src/run_all_extract.py --mode test
    ./venv-linux/bin/python src/run_all_extract.py --mode production
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from settings import load_settings, SHARED_CONFIG_DIR
from services.hive_service import HiveService, HiveCredentials
from services.sheets_service import SheetsService
from config import COLUMN_ORDER
from logger_setup import setup_logger, get_logger

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


CANONICAL_KEYS = COLUMN_ORDER["all_enriched"]


def _order(row: dict) -> list:
    return [row.get(k, "") for k in CANONICAL_KEYS]


def _ensure_tab_from_template(sheets: SheetsService, tab_name: str, template_tab: str = "All") -> None:
    """Ensure `tab_name` exists. If missing, create a small blank tab and copy
    rows 1-4 (headers + metadata) from `template_tab`. Values only — formulas
    are not copied. Enough to verify layout during testing.
    """
    log = get_logger()
    svc = sheets._shared.service
    spreadsheet_id = sheets._shared._default_spreadsheet_id

    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if tab_name in existing:
        return
    if template_tab not in existing:
        raise RuntimeError(f"Template tab '{template_tab}' not found — cannot auto-create '{tab_name}'")

    log.info(f"Creating blank '{tab_name}' tab + copying headers from '{template_tab}' ...")
    # Add blank sheet with small grid (avoid 10M cell limit)
    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "addSheet": {
                "properties": {
                    "title": tab_name,
                    "gridProperties": {"rowCount": 20000, "columnCount": 30},
                }
            }
        }]},
    ).execute()
    # Copy header rows 1-4 from template
    hdr = svc.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'{template_tab}'!A1:AD4",
    ).execute().get("values", [])
    if hdr:
        svc.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{tab_name}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": hdr},
        ).execute()


def _clear_and_write(sheets: SheetsService, tab_name: str, rows: list) -> int:
    """Clear A5:Z of the tab, then write rows starting at A5 with canonical order."""
    log = get_logger()
    svc = sheets._shared.service
    spreadsheet_id = sheets._shared._default_spreadsheet_id

    log.info(f"Clearing '{tab_name}'!A5:Z50000 ...")
    svc.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A5:Z50000",
    ).execute()

    values = [_order(r) for r in rows]
    log.info(f"Writing {len(values):,} rows to '{tab_name}'!A5 ...")
    result = svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A5",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    return int(result.get("updatedRows", 0) or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preview", "test", "production"), default="preview")
    parser.add_argument("--client", default="LSC")
    parser.add_argument("--from-date", default="2020-01-01")
    parser.add_argument("--to-date", default=None)
    args = parser.parse_args()

    setup_logger()
    log = get_logger()

    settings = load_settings()
    if not settings.is_configured():
        print("Not configured. Run: python src/main.py --setup")
        sys.exit(1)

    master = MasterConfig()
    client_config = master.get_client(args.client)

    hive = HiveService(HiveCredentials(
        api_key=settings.hive_api_key,
        user_id=client_config.hive.user_id,
        workspace_id=client_config.hive.workspace_id,
    ))
    if not hive.test_connection():
        log.error("Could not connect to Hive API")
        sys.exit(1)

    from_date = date.fromisoformat(args.from_date)
    to_date = date.fromisoformat(args.to_date) if args.to_date else date.today()

    log.info(f"Mode: {args.mode}")
    log.info(f"Date range: {from_date} to {to_date}")

    # role_lookup not yet wired — Role will be blank
    rows = hive.get_enriched_monthly_entries(from_date, to_date, role_lookup=None)

    total_hours = round(sum(r.get("Hours", 0) for r in rows), 2)
    unique_people = len(set(r.get("Person", "") for r in rows))
    unique_projects = len(set(r.get("Project", "") for r in rows))
    unique_months = len(set(r.get("Date", "") for r in rows))

    log.info(f"Rows:            {len(rows):,}")
    log.info(f"Total hours:     {total_hours:,.2f}")
    log.info(f"Unique people:   {unique_people}")
    log.info(f"Unique projects: {unique_projects}")
    log.info(f"Unique months:   {unique_months}")

    # --------------- preview mode: write first 100 to file ---------------
    if args.mode == "preview":
        out_path = Path(__file__).parent.parent / "output" / "all_enriched_preview.json"
        out_path.parent.mkdir(exist_ok=True)
        sample = rows[:100]
        with open(out_path, "w") as f:
            json.dump({
                "mode": "preview",
                "client": args.client,
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "totals": {
                    "rows": len(rows),
                    "hours": total_hours,
                    "people": unique_people,
                    "projects": unique_projects,
                    "months": unique_months,
                },
                "canonical_columns": CANONICAL_KEYS,
                "sample_first_100_rows": sample,
            }, f, indent=2, default=str)
        log.info(f"Preview saved: {out_path}")
        return

    # --------------- test / production: sheet write ---------------
    # SA key always lives under clients/BosOpt/. Per-client access is handled
    # by impersonate_email (DWD) for ELW/BHCP or SA-direct sharing for
    # SA-approved clients. Non-approved clients fall back to user OAuth.
    spreadsheet_id = client_config.sheets.hive_extract_sheet_id
    impersonate_email = getattr(client_config.client, "sa_email_impersonation", "") or None
    from pathlib import Path as _Path
    import sys as _sys
    _shared = str(_Path(__file__).parent.parent.parent / "_shared_config")
    if _shared not in _sys.path:
        _sys.path.insert(0, _shared)
    from integrations.sa_policy import prefer_oauth_for
    sheets = SheetsService(spreadsheet_id, credential_ref="BosOpt",
                           impersonate_email=impersonate_email,
                           prefer_oauth=prefer_oauth_for(args.client))
    if not sheets.authenticate() or not sheets.test_access():
        log.error("Could not authenticate to Google Sheets")
        sys.exit(1)

    if args.mode == "test":
        _ensure_tab_from_template(sheets, "All_TEST", template_tab="All")
        written = _clear_and_write(sheets, "All_TEST", rows)
        log.info(f"TEST write complete: {written} rows to All_TEST")
        log.info("Inspect the All_TEST tab, then re-run with --mode production")
        return

    # production
    written_all = _clear_and_write(sheets, "All", rows)
    log.info(f"All: {written_all} rows written")

    # Current-month filter
    today = date.today()
    current_month_key = f"{today.year:04d}-{today.month:02d}-01"
    month_rows = [r for r in rows if r.get("Date") == current_month_key]
    log.info(f"Current month filter: {len(month_rows):,} rows for {current_month_key}")

    written_month = _clear_and_write(sheets, "Month", month_rows)
    log.info(f"Month: {written_month} rows written")

    log.info("Production write complete.")


if __name__ == "__main__":
    main()
