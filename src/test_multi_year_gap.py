"""Multi-year comparison of API (with includeArchivedProjects=true) vs UI baseline CSVs.

UI baselines are the "HIVE Data Sets - ALL_YYYY.csv" exports downloaded from
the Google Sheet — these are the Hive UI exports that were cut/pasted into the
sheet. The CSV has metadata in rows 1-3 and data headers on row 4 (or 5).

Usage:
    cd HIVE_Extract
    ./venv-linux/bin/python src/test_multi_year_gap.py
"""

import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))

from settings import load_settings, SHARED_CONFIG_DIR
from services.hive_service import HiveService, HiveCredentials
from logger_setup import setup_logger, get_logger
from test_include_archived_flag import fetch_entries, summarize_api

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


UI_PATH_TEMPLATE = "HIVE Data Sets - ALL_{year}.csv"


def read_sheet_export(path: Path) -> Dict[str, Any]:
    """Parse the 'HIVE Data Sets - ALL_YYYY.csv' format.

    Row 3 has the pre-computed summary (# Rows + total Hours).
    Row 4 is the header; row 5 also a header (pasted), data starts row 6.
    We scan for the first row where column A is 'Person' AND the next row
    ALSO starts with 'Person' — that second one is the pasted header and
    real data starts immediately after.
    """
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    # Find summary row (has "# Rows" somewhere and a number)
    summary_hours = None
    summary_rows = None
    for r in rows[:5]:
        joined = ",".join(r)
        if "# Rows" in joined:
            # Find the position of "# Rows" and grab the next two cells
            for i, cell in enumerate(r):
                if cell.strip() == "# Rows" and i + 2 < len(r):
                    try:
                        summary_rows = int(r[i + 1].replace(",", ""))
                        summary_hours = float(r[i + 2].replace(",", ""))
                    except (ValueError, IndexError):
                        pass
                    break

    # Locate header row: look for a row starting with "Person" where the
    # NEXT row ALSO starts with "Person" — data starts after the pair.
    # If only one "Person" row exists, data starts right after it.
    header_idx = None
    for i in range(len(rows) - 1):
        if rows[i] and rows[i][0].strip() == "Person":
            header_idx = i
            # If next row also starts with Person, skip it too
            if i + 1 < len(rows) and rows[i + 1] and rows[i + 1][0].strip() == "Person":
                header_idx = i + 1
            break

    if header_idx is None:
        raise ValueError(f"Could not locate header row in {path}")

    headers = [h.strip() for h in rows[header_idx]]
    data_rows = rows[header_idx + 1:]

    try:
        person_col = headers.index("Person")
    except ValueError:
        person_col = 0
    try:
        hours_col = headers.index("Hours")
    except ValueError:
        hours_col = None

    total_hours = 0.0
    row_count = 0
    by_person_hours: Dict[str, float] = defaultdict(float)
    by_person_rows: Dict[str, int] = defaultdict(int)

    for r in data_rows:
        if not r or not any(c.strip() for c in r):
            continue
        person = r[person_col].strip() if person_col < len(r) else ""
        if not person:
            continue
        try:
            hrs = float(r[hours_col].replace(",", "")) if hours_col is not None and hours_col < len(r) else 0.0
        except (ValueError, TypeError):
            hrs = 0.0
        row_count += 1
        total_hours += hrs
        by_person_hours[person] += hrs
        by_person_rows[person] += 1

    return {
        "rows": row_count,
        "total_hours": round(total_hours, 2),
        "by_person_hours": {p: round(h, 2) for p, h in by_person_hours.items()},
        "by_person_rows": dict(by_person_rows),
        "summary_rows": summary_rows,
        "summary_hours": summary_hours,
    }


def print_year(year: int, ui: Dict[str, Any], api: Dict[str, Any]) -> float:
    print()
    print("=" * 76)
    print(f"  {year}")
    print("=" * 76)
    print(f"  UI summary row claims: {ui.get('summary_rows')} rows / {ui.get('summary_hours')} hrs")
    print(f"  UI parsed rows:        {ui['rows']:,} rows / {ui['total_hours']:,.2f} hrs")
    print(f"  API WITH flag:         {api['rows']:,} rows / {api['total_hours']:,.2f} hrs")
    gap = round(api['total_hours'] - ui['total_hours'], 2)
    print(f"  Gap (API - UI):        {gap:+,.2f} hrs")

    # Per-person gaps, largest-abs first
    print()
    print(f"  {'Person':<30s} {'UI hrs':>10s} {'API hrs':>10s} {'Diff':>10s}")
    print(f"  {'-' * 30} {'-' * 10} {'-' * 10} {'-' * 10}")
    all_people = set(ui["by_person_hours"]) | set(api["by_person_hours"])
    rows = []
    for p in all_people:
        u = ui["by_person_hours"].get(p, 0.0)
        a = api["by_person_hours"].get(p, 0.0)
        d = round(a - u, 2)
        rows.append((p, u, a, d))
    rows.sort(key=lambda x: abs(x[3]), reverse=True)
    for p, u, a, d in rows:
        flag = "" if abs(d) < 0.5 else "  <-- GAP"
        print(f"  {p:<30s} {u:>10,.2f} {a:>10,.2f} {d:>+10,.2f}{flag}")

    return gap


def main() -> None:
    setup_logger()
    get_logger()

    settings = load_settings()
    master = MasterConfig()
    cfg = master.get_client("LSC")
    hive = HiveService(HiveCredentials(
        api_key=settings.hive_api_key,
        user_id=cfg.hive.user_id,
        workspace_id=cfg.hive.workspace_id,
    ))
    if not hive.test_connection():
        print("Could not connect to Hive")
        sys.exit(1)

    output_dir = Path(__file__).parent.parent / "output"
    results = {}

    for year in (2024, 2025, 2026):
        ui_path = output_dir / UI_PATH_TEMPLATE.format(year=year)
        if not ui_path.exists():
            print(f"SKIP {year}: baseline {ui_path} not found")
            continue
        print(f"\nParsing UI baseline for {year}: {ui_path.name}")
        ui = read_sheet_export(ui_path)

        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)
        today = date.today()
        if to_date > today:
            to_date = today

        print(f"Fetching {year} entries WITH includeArchivedProjects=true "
              f"({from_date} to {to_date})...")
        api_entries = fetch_entries(hive, from_date, to_date, include_archived_projects=True)
        api = summarize_api(api_entries)

        gap = print_year(year, ui, api)
        results[year] = gap

    print()
    print("=" * 76)
    print("  SUMMARY (API WITH flag vs UI)")
    print("=" * 76)
    for y, g in results.items():
        verdict = "MATCH" if abs(g) < 1.0 else "MISMATCH"
        print(f"  {y}: gap {g:+,.2f} hrs  — {verdict}")


if __name__ == "__main__":
    main()
