#!/usr/bin/env python3
"""Fetch 2025 timesheet data from Hive API and save as CSV for comparison."""

import sys
from pathlib import Path
from datetime import date

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from settings import load_settings
from services.hive_service import HiveService, HiveCredentials
from logger_setup import setup_logger


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

    print("Connecting to Hive API...")
    if not hive.test_connection():
        print("ERROR: Cannot connect to Hive API")
        sys.exit(1)
    print("Connected.\n")

    # Fetch all of 2025
    from_date = date(2025, 1, 1)
    to_date = date(2025, 12, 31)

    print(f"Fetching timesheet report CSV: {from_date} to {to_date}...")
    csv_string = hive.get_year_timesheet_report_raw(2025)

    if not csv_string:
        print("ERROR: Empty response from API")
        sys.exit(1)

    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "api_2025_full_year.csv"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(csv_string)

    # Count rows (minus header)
    lines = csv_string.strip().split("\n")
    row_count = len(lines) - 1
    print(f"\nSaved {row_count} rows to: {output_path}")

    # Quick summary of total hours
    import csv
    import io
    reader = csv.DictReader(io.StringIO(csv_string))
    headers = reader.fieldnames or []
    print(f"Columns: {headers}")

    total_hours = 0.0
    for row in reader:
        for col in ["Total Hours", "Hours", "Total"]:
            if col in row and row[col]:
                try:
                    total_hours += float(row[col].replace(",", ""))
                    break
                except ValueError:
                    pass

    print(f"Total Hours: {total_hours:.2f}")


if __name__ == "__main__":
    main()
