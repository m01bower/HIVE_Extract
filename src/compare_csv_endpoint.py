"""Compare Hive API CSV vs Web UI CSV download for 2025.

Filters out zero-hour rows from both sides, then compares:
1. Row counts and total hours
2. Missing/extra rows
3. Hour value differences on matched rows
"""

import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

OUTPUT_DIR = Path(__file__).parent.parent / "output"
API_CSV = OUTPUT_DIR / "test_api_2025_2026-03-09.csv"
UI_CSV = OUTPUT_DIR / "Export_Timesheet_Reporting_2025.csv"


def load_csv(filepath: Path) -> list[dict]:
    """Load CSV file, filtering out rows with zero or missing hours."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        skipped = 0
        for row in reader:
            hours_str = row.get("Hours", "").strip()
            if not hours_str:
                skipped += 1
                continue
            try:
                hours = float(hours_str)
                if hours == 0.0:
                    skipped += 1
                    continue
            except ValueError:
                skipped += 1
                continue
            rows.append(row)
        print(f"  Loaded {len(rows)} rows (skipped {skipped} with zero/missing hours)")
        return rows


def make_key(row: dict) -> str:
    """Create a matching key from Person + Date + Project + Category."""
    parts = [
        row.get("Person", "").strip(),
        row.get("Date", "").strip(),
        row.get("Project", "").strip(),
        row.get("Category", "").strip(),
    ]
    return "|".join(parts)


def main():
    print(f"API CSV: {API_CSV}")
    print(f"UI CSV:  {UI_CSV}")

    if not API_CSV.exists():
        print(f"ERROR: {API_CSV} not found. Run test_csv_endpoint.py first.")
        sys.exit(1)
    if not UI_CSV.exists():
        print(f"ERROR: {UI_CSV} not found.")
        sys.exit(1)

    print(f"\nLoading API CSV...")
    api_rows = load_csv(API_CSV)
    print(f"Loading UI CSV...")
    ui_rows = load_csv(UI_CSV)

    # Totals
    api_total = sum(float(r.get("Hours", 0)) for r in api_rows)
    ui_total = sum(float(r.get("Hours", 0)) for r in ui_rows)

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY")
    print(f"{'=' * 70}")
    print(f"  {'Source':<25} {'Rows':>8} {'Total Hours':>14}")
    print(f"  {'-' * 25} {'-' * 8} {'-' * 14}")
    print(f"  {'Web UI CSV':<25} {len(ui_rows):>8} {ui_total:>14,.2f}")
    print(f"  {'API CSV':<25} {len(api_rows):>8} {api_total:>14,.2f}")
    print(f"  {'Difference (API - UI)':<25} {len(api_rows) - len(ui_rows):>+8} {api_total - ui_total:>+14,.2f}")

    # Index by key
    api_idx: dict[str, list[dict]] = defaultdict(list)
    ui_idx: dict[str, list[dict]] = defaultdict(list)

    for r in api_rows:
        api_idx[make_key(r)].append(r)
    for r in ui_rows:
        ui_idx[make_key(r)].append(r)

    api_keys = set(api_idx.keys())
    ui_keys = set(ui_idx.keys())

    only_api = api_keys - ui_keys
    only_ui = ui_keys - api_keys
    common = api_keys & ui_keys

    print(f"\n  Matched rows (by key):   {len(common)}")
    print(f"  Only in API:             {len(only_api)}")
    print(f"  Only in UI:              {len(only_ui)}")

    # --- Rows only in UI (missing from API) ---
    if only_ui:
        only_ui_hours = sum(float(ui_idx[k][0].get("Hours", 0)) for k in only_ui)
        print(f"\n{'=' * 70}")
        print(f"  ROWS ONLY IN WEB UI ({len(only_ui)} rows, {only_ui_hours:,.2f} hours)")
        print(f"{'=' * 70}")
        print(f"  {'Person':<25} {'Date':<12} {'Hours':>8} {'Project':<30}")
        print(f"  {'-' * 25} {'-' * 12} {'-' * 8} {'-' * 30}")
        for k in sorted(only_ui):
            r = ui_idx[k][0]
            print(f"  {r.get('Person', ''):<25} {r.get('Date', ''):<12} {r.get('Hours', ''):>8} {r.get('Project', '')[:30]:<30}")
            if len(list(sorted(only_ui))) > 30:
                break

    # --- Rows only in API (extra in API) ---
    if only_api:
        only_api_hours = sum(float(api_idx[k][0].get("Hours", 0)) for k in only_api)
        print(f"\n{'=' * 70}")
        print(f"  ROWS ONLY IN API ({len(only_api)} rows, {only_api_hours:,.2f} hours)")
        print(f"{'=' * 70}")
        print(f"  {'Person':<25} {'Date':<12} {'Hours':>8} {'Project':<30}")
        print(f"  {'-' * 25} {'-' * 12} {'-' * 8} {'-' * 30}")
        count = 0
        for k in sorted(only_api):
            r = api_idx[k][0]
            print(f"  {r.get('Person', ''):<25} {r.get('Date', ''):<12} {r.get('Hours', ''):>8} {r.get('Project', '')[:30]:<30}")
            count += 1
            if count >= 30:
                remaining = len(only_api) - 30
                if remaining > 0:
                    print(f"  ... and {remaining} more")
                break

    # --- Hour differences on matched rows ---
    hour_diffs = []
    for k in sorted(common):
        api_hours = float(api_idx[k][0].get("Hours", 0))
        ui_hours = float(ui_idx[k][0].get("Hours", 0))
        diff = round(api_hours - ui_hours, 4)
        if abs(diff) > 0.001:
            hour_diffs.append({
                "key": k,
                "api_hours": api_hours,
                "ui_hours": ui_hours,
                "diff": diff,
                "person": api_idx[k][0].get("Person", ""),
                "date": api_idx[k][0].get("Date", ""),
                "project": api_idx[k][0].get("Project", ""),
            })

    total_hour_diff = sum(d["diff"] for d in hour_diffs)

    print(f"\n{'=' * 70}")
    print(f"  HOUR DIFFERENCES ON MATCHED ROWS")
    print(f"{'=' * 70}")
    print(f"  Rows with different hours: {len(hour_diffs)}")
    print(f"  Net hour difference:       {total_hour_diff:+,.2f}")

    if hour_diffs:
        # Sort by absolute diff descending
        hour_diffs.sort(key=lambda d: abs(d["diff"]), reverse=True)

        over = [d for d in hour_diffs if d["diff"] > 0]
        under = [d for d in hour_diffs if d["diff"] < 0]
        print(f"  API over-reports:          {len(over)} rows ({sum(d['diff'] for d in over):+,.2f} hrs)")
        print(f"  API under-reports:         {len(under)} rows ({sum(d['diff'] for d in under):+,.2f} hrs)")

        show = min(len(hour_diffs), 30)
        print(f"\n  Top {show} differences (by magnitude):")
        print(f"  {'Person':<22} {'Date':<12} {'UI Hrs':>8} {'API Hrs':>8} {'Diff':>8} {'Project':<25}")
        print(f"  {'-' * 22} {'-' * 12} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 25}")
        for d in hour_diffs[:show]:
            print(
                f"  {d['person']:<22} {d['date']:<12} "
                f"{d['ui_hours']:>8.2f} {d['api_hours']:>8.2f} {d['diff']:>+8.2f} "
                f"{d['project'][:25]:<25}"
            )

    # --- Per-person hour comparison ---
    api_person_hrs = defaultdict(float)
    ui_person_hrs = defaultdict(float)
    for r in api_rows:
        api_person_hrs[r.get("Person", "")] += float(r.get("Hours", 0))
    for r in ui_rows:
        ui_person_hrs[r.get("Person", "")] += float(r.get("Hours", 0))

    all_people = sorted(set(api_person_hrs.keys()) | set(ui_person_hrs.keys()))

    print(f"\n{'=' * 70}")
    print(f"  PER-PERSON HOUR TOTALS")
    print(f"{'=' * 70}")
    print(f"  {'Person':<25} {'UI Hrs':>10} {'API Hrs':>10} {'Diff':>10}")
    print(f"  {'-' * 25} {'-' * 10} {'-' * 10} {'-' * 10}")
    for p in all_people:
        ui_h = ui_person_hrs.get(p, 0)
        api_h = api_person_hrs.get(p, 0)
        diff = api_h - ui_h
        flag = " ***" if abs(diff) > 0.01 else ""
        print(f"  {p:<25} {ui_h:>10,.2f} {api_h:>10,.2f} {diff:>+10,.2f}{flag}")

    print(f"  {'-' * 25} {'-' * 10} {'-' * 10} {'-' * 10}")
    print(f"  {'TOTAL':<25} {ui_total:>10,.2f} {api_total:>10,.2f} {api_total - ui_total:>+10,.2f}")

    # --- Final verdict ---
    print(f"\n{'=' * 70}")
    if len(only_ui) == 0 and len(only_api) == 0 and len(hour_diffs) == 0:
        print(f"  VERDICT: PERFECT MATCH")
    elif len(only_ui) == 0 and len(hour_diffs) == 0:
        print(f"  VERDICT: API has extra rows but all matched rows agree on hours")
    else:
        issues = []
        if only_ui:
            issues.append(f"{len(only_ui)} rows missing from API")
        if only_api:
            issues.append(f"{len(only_api)} extra rows in API")
        if hour_diffs:
            issues.append(f"{len(hour_diffs)} rows with different hours ({total_hour_diff:+,.2f} hrs)")
        print(f"  VERDICT: DIFFERENCES FOUND — {'; '.join(issues)}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
