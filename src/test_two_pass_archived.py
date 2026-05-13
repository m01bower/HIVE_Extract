"""Two-pass archived-actions test — validates Hive's 2026-04-21 guidance.

Hive confirmed the residual gap for Michael Cole / Candace Famiglietti sits on
individually-archived action cards (action-level `archived: true`) — distinct
from `includeArchivedProjects`. Their fix: run getActionsByWorkspace twice,
once with `archived: false` (default) and once with `archived: true`, both
passing `includeArchivedProjects: true`. Union + dedup the results.

Compares the combined result against the UI baselines for 2024/2025/2026.

Usage:
    cd HIVE_Extract
    ./venv-linux/bin/python src/test_two_pass_archived.py
"""

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from settings import load_settings, SHARED_CONFIG_DIR
from services.hive_service import HiveService, HiveCredentials
from logger_setup import setup_logger, get_logger
from test_multi_year_gap import read_sheet_export, UI_PATH_TEMPLATE

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


QUERY = """
query GetActions($workspaceId: ID!, $first: Int, $after: ID,
                 $includeArchivedProjects: Boolean, $archived: Boolean) {
  getActionsByWorkspace(
    workspaceId: $workspaceId,
    first: $first,
    after: $after,
    excludeCompletedActions: false,
    includeArchivedProjects: $includeArchivedProjects,
    archived: $archived
  ) {
    edges {
      node {
        _id
        title
        project { _id name }
        timeTracking {
          actualList { id userId time date categoryId }
        }
      }
      cursor
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def fetch_pass(
    hive: HiveService,
    from_date: date,
    to_date: date,
    archived: bool,
) -> List[Dict[str, Any]]:
    """Run one paginated pass of getActionsByWorkspace with the given archived value."""
    workspace_id = hive.credentials.workspace_id
    user_lookup = hive.get_workspace_users()
    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    entries: List[Dict[str, Any]] = []
    cursor = None
    page = 0
    total_actions = 0

    while True:
        page += 1
        variables: Dict[str, Any] = {
            "workspaceId": workspace_id,
            "first": 100,
            "includeArchivedProjects": True,
            "archived": archived,
        }
        if cursor:
            variables["after"] = cursor

        result = hive._execute_query(QUERY, variables)
        conn = result.get("getActionsByWorkspace", {})
        edges = conn.get("edges", [])
        total_actions += len(edges)

        for edge in edges:
            action = edge.get("node") or {}
            action_id = action.get("_id", "")
            tracking = action.get("timeTracking") or {}
            for entry in tracking.get("actualList") or []:
                raw_date = entry.get("date", "") or ""
                if isinstance(raw_date, str) and "T" in raw_date:
                    raw_date = raw_date.split("T")[0]
                if not raw_date or raw_date < from_str or raw_date > to_str:
                    continue

                uid = entry.get("userId", "")
                info = user_lookup.get(uid) or hive.resolve_user(uid) or {}

                entries.append({
                    "action_id": action_id,
                    "entry_id": entry.get("id", ""),
                    "person": info.get("fullName", "") or uid,
                    "date": raw_date,
                    "minutes": round((entry.get("time", 0) or 0) / 60, 2),
                })

        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        cursor = info.get("endCursor")

    print(f"  pass archived={archived}: {page} pages, {total_actions} actions, "
          f"{len(entries)} in-range entries")
    return entries


def dedup(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Dedup by (action_id, entry_id)."""
    seen: Set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for e in entries:
        key = (e["action_id"], e["entry_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def summarize(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_person_hours: Dict[str, float] = defaultdict(float)
    total_minutes = 0.0
    for e in entries:
        total_minutes += e["minutes"]
        by_person_hours[e["person"]] += e["minutes"] / 60
    return {
        "rows": len(entries),
        "total_hours": round(total_minutes / 60, 2),
        "by_person_hours": {p: round(h, 2) for p, h in by_person_hours.items()},
    }


def print_year(year: int, ui: Dict[str, Any], api: Dict[str, Any]) -> float:
    print()
    print("=" * 76)
    print(f"  {year}")
    print("=" * 76)
    print(f"  UI baseline:    {ui['rows']:,} rows / {ui['total_hours']:,.2f} hrs")
    print(f"  API two-pass:   {api['rows']:,} rows / {api['total_hours']:,.2f} hrs")
    gap = round(api['total_hours'] - ui['total_hours'], 2)
    print(f"  Gap (API - UI): {gap:+,.2f} hrs")

    focus = ["Michael Cole", "Candace Famiglietti",
             "Irma Frias", "Christine Van Fossen"]
    print()
    print(f"  {'Person':<28s} {'UI hrs':>10s} {'API hrs':>10s} {'Diff':>10s}")
    for name in focus:
        u = ui["by_person_hours"].get(name, 0.0)
        a = api["by_person_hours"].get(name, 0.0)
        d = round(a - u, 2)
        flag = "" if abs(d) < 0.5 else "  <-- GAP"
        print(f"  {name:<28s} {u:>10,.2f} {a:>10,.2f} {d:>+10,.2f}{flag}")

    # Any other person with a material gap
    others = []
    all_people = set(ui["by_person_hours"]) | set(api["by_person_hours"])
    for p in all_people:
        if p in focus:
            continue
        u = ui["by_person_hours"].get(p, 0.0)
        a = api["by_person_hours"].get(p, 0.0)
        d = round(a - u, 2)
        if abs(d) >= 0.5:
            others.append((p, u, a, d))
    if others:
        print(f"\n  Other gaps >0.5 hrs:")
        for p, u, a, d in sorted(others, key=lambda x: abs(x[3]), reverse=True):
            print(f"  {p:<28s} {u:>10,.2f} {a:>10,.2f} {d:>+10,.2f}  <-- GAP")

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
        print("Could not connect")
        sys.exit(1)

    output_dir = Path(__file__).parent.parent / "output"
    results = {}

    for year in (2024, 2025, 2026):
        ui_path = output_dir / UI_PATH_TEMPLATE.format(year=year)
        if not ui_path.exists():
            print(f"SKIP {year}: baseline missing")
            continue

        print(f"\n---- {year} ----")
        ui = read_sheet_export(ui_path)

        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)
        if to_date > date.today():
            to_date = date.today()

        active = fetch_pass(hive, from_date, to_date, archived=False)
        arch = fetch_pass(hive, from_date, to_date, archived=True)
        combined = dedup(active + arch)
        print(f"  combined (after dedup): {len(combined)} entries "
              f"({len(active)} + {len(arch)} − {len(active) + len(arch) - len(combined)} dupes)")

        api = summarize(combined)
        gap = print_year(year, ui, api)
        results[year] = gap

    print()
    print("=" * 76)
    print("  SUMMARY (two-pass API vs UI)")
    print("=" * 76)
    for y, g in results.items():
        verdict = "MATCH" if abs(g) < 1.0 else "MISMATCH"
        print(f"  {y}: gap {g:+,.2f} hrs  — {verdict}")


if __name__ == "__main__":
    main()
