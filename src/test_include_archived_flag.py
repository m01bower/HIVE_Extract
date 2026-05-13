"""Test Hive's suggested fix: pass includeArchivedProjects: true to getActionsByWorkspace.

Runs the same pagination as hive_service.get_time_entries() but adds the
new `includeArchivedProjects: true` argument that Hive just surfaced in the
GraphQL schema. Compares the resulting totals against the UI CSV export and
flags the former-employee rows (Irma Frias, Christine Van Fossen, Michael Cole)
that were specifically missing in prior tests.

Does NOT touch production code — this is a read-only verification.

Usage:
    cd HIVE_Extract
    ./venv-linux/bin/python src/test_include_archived_flag.py [--year 2025]
"""

import argparse
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

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


QUERY_WITH_FLAG = """
query GetActions($workspaceId: ID!, $first: Int, $after: ID, $includeArchivedProjects: Boolean) {
  getActionsByWorkspace(
    workspaceId: $workspaceId,
    first: $first,
    after: $after,
    excludeCompletedActions: false,
    includeArchivedProjects: $includeArchivedProjects
  ) {
    edges {
      node {
        _id
        title
        project { _id name parentProject }
        timeTracking {
          actualList { id userId time date description categoryId }
        }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def fetch_entries(hive: HiveService, from_date: date, to_date: date,
                  include_archived_projects: bool) -> List[Dict[str, Any]]:
    """Paginate getActionsByWorkspace, optionally including archived projects."""
    workspace_id = hive.credentials.workspace_id
    user_lookup = hive.get_workspace_users()
    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    all_entries: List[Dict[str, Any]] = []
    cursor = None
    page = 0
    total_actions = 0

    while True:
        page += 1
        variables: Dict[str, Any] = {
            "workspaceId": workspace_id,
            "first": 100,
            "includeArchivedProjects": include_archived_projects,
        }
        if cursor:
            variables["after"] = cursor

        result = hive._execute_query(QUERY_WITH_FLAG, variables)
        connection = result.get("getActionsByWorkspace", {})
        edges = connection.get("edges", [])
        total_actions += len(edges)

        for edge in edges:
            action = edge.get("node") or {}
            tracking = action.get("timeTracking") or {}
            for entry in tracking.get("actualList") or []:
                raw_date = entry.get("date", "") or ""
                if isinstance(raw_date, str) and "T" in raw_date:
                    raw_date = raw_date.split("T")[0]
                if not raw_date or raw_date < from_str or raw_date > to_str:
                    continue

                uid = entry.get("userId", "")
                info = user_lookup.get(uid) or hive.resolve_user(uid) or {}
                project = action.get("project") or {}

                all_entries.append({
                    "person": info.get("fullName", "") or uid,
                    "email": info.get("email", ""),
                    "project": project.get("name", ""),
                    "date": raw_date,
                    "minutes": round((entry.get("time", 0) or 0) / 60, 2),
                })

        info = connection.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        cursor = info.get("endCursor")
        print(f"    page {page} scanned ({total_actions} actions, {len(all_entries)} entries so far)")

    print(f"  Done: {page} pages, {total_actions} actions, {len(all_entries)} in-range entries.")
    return all_entries


def read_ui_csv(path: Path) -> Dict[str, Any]:
    """Return totals + by-person breakdown from the UI timesheet CSV."""
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    total_hours = 0.0
    by_person = defaultdict(float)
    by_person_rows = defaultdict(int)
    valid = 0

    for r in rows:
        try:
            hrs = float((r.get("Hours") or "0").replace(",", "") or 0)
        except ValueError:
            hrs = 0.0
        person = r.get("Person", "").strip()
        if not person and not hrs:
            continue
        valid += 1
        total_hours += hrs
        by_person[person] += hrs
        by_person_rows[person] += 1

    return {
        "rows": valid,
        "total_hours": round(total_hours, 2),
        "by_person_hours": {p: round(h, 2) for p, h in by_person.items()},
        "by_person_rows": dict(by_person_rows),
    }


def summarize_api(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_person_hours = defaultdict(float)
    by_person_rows = defaultdict(int)
    total_minutes = 0.0
    for e in entries:
        total_minutes += e["minutes"]
        by_person_hours[e["person"]] += e["minutes"] / 60
        by_person_rows[e["person"]] += 1
    return {
        "rows": len(entries),
        "total_hours": round(total_minutes / 60, 2),
        "by_person_hours": {p: round(h, 2) for p, h in by_person_hours.items()},
        "by_person_rows": dict(by_person_rows),
    }


def print_comparison(label: str, api: Dict[str, Any], ui: Dict[str, Any]) -> float:
    print()
    print("=" * 72)
    print(f"  {label}")
    print("=" * 72)
    print(f"  {'Source':<30s} {'Rows':>8s} {'Total Hours':>14s}")
    print(f"  {'-' * 30} {'-' * 8} {'-' * 14}")
    print(f"  {'UI CSV (daily entries)':<30s} {ui['rows']:>8,d} {ui['total_hours']:>14,.2f}")
    print(f"  {'API (getActionsByWorkspace)':<30s} {api['rows']:>8,d} {api['total_hours']:>14,.2f}")

    hrs_diff = round(api['total_hours'] - ui['total_hours'], 2)
    print()
    print(f"  Hour gap (API - UI): {hrs_diff:+,.2f}")

    focus = ["Irma Frias", "Christine Van Fossen", "Michael Cole"]
    print()
    print(f"  Former-employee focus (expected to be missing before fix):")
    print(f"    {'Person':<28s} {'UI hrs':>10s} {'API hrs':>10s} {'Diff':>10s}")
    for name in focus:
        ui_h = ui["by_person_hours"].get(name, 0.0)
        api_h = api["by_person_hours"].get(name, 0.0)
        diff = round(api_h - ui_h, 2)
        flag = "" if abs(diff) < 0.5 else "  <-- GAP"
        print(f"    {name:<28s} {ui_h:>10,.2f} {api_h:>10,.2f} {diff:>+10,.2f}{flag}")

    return hrs_diff


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--client", type=str, default="LSC")
    parser.add_argument("--skip-baseline", action="store_true",
                        help="Skip the without-flag run (saves ~60s)")
    args = parser.parse_args()

    setup_logger()
    get_logger()

    settings = load_settings()
    if not settings.is_configured():
        print("ERROR: Not configured. Run: python src/main.py --setup")
        sys.exit(1)

    master = MasterConfig()
    cfg = master.get_client(args.client)
    hive = HiveService(HiveCredentials(
        api_key=settings.hive_api_key,
        user_id=cfg.hive.user_id,
        workspace_id=cfg.hive.workspace_id,
    ))
    if not hive.test_connection():
        print("Could not connect to Hive")
        sys.exit(1)

    from_date = date(args.year, 1, 1)
    to_date = date(args.year, 12, 31)
    if to_date > date.today():
        to_date = date.today()

    ui_path = Path(__file__).parent.parent / "output" / f"UI Export_Timesheet_Reporting_{args.year}.csv"
    if not ui_path.exists():
        print(f"WARNING: UI baseline CSV missing: {ui_path}")
        ui_summary = {"rows": 0, "total_hours": 0.0, "by_person_hours": {}, "by_person_rows": {}}
    else:
        ui_summary = read_ui_csv(ui_path)
        print(f"UI baseline: {ui_summary['rows']} rows, {ui_summary['total_hours']:,.2f} hrs")

    # ---- Run 1: WITH the new flag ---------------------------------------
    print()
    print(f"Fetching {args.year} entries WITH includeArchivedProjects=true...")
    with_entries = fetch_entries(hive, from_date, to_date, include_archived_projects=True)
    with_summary = summarize_api(with_entries)
    with_diff = print_comparison(
        f"WITH includeArchivedProjects=true — {args.year}",
        with_summary, ui_summary,
    )

    # ---- Run 2: WITHOUT the flag (the previous broken behavior) ---------
    without_diff = None
    if not args.skip_baseline:
        print()
        print(f"Fetching {args.year} entries WITHOUT the flag (for comparison)...")
        without_entries = fetch_entries(hive, from_date, to_date, include_archived_projects=False)
        without_summary = summarize_api(without_entries)
        without_diff = print_comparison(
            f"WITHOUT includeArchivedProjects (previous behavior) — {args.year}",
            without_summary, ui_summary,
        )

    # ---- Verdict --------------------------------------------------------
    print()
    print("=" * 72)
    print("  VERDICT")
    print("=" * 72)
    if without_diff is not None:
        print(f"  WITHOUT flag gap: {without_diff:+,.2f} hrs")
    print(f"  WITH flag gap:    {with_diff:+,.2f} hrs")
    if abs(with_diff) < 1.0:
        print("  RESULT: FIX WORKS — API now matches UI within 1 hour.")
    elif without_diff is not None and abs(with_diff) < abs(without_diff) * 0.2:
        print("  RESULT: PARTIAL FIX — gap shrank materially but not closed.")
    else:
        print("  RESULT: NO FIX — gap unchanged; Hive is still guessing.")


if __name__ == "__main__":
    main()
