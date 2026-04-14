"""Introspect the Hive GraphQL schema to discover available queries/mutations.

Looks for anything related to timesheet, CSV, export, or widget.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from settings import load_settings, SHARED_CONFIG_DIR
from services.hive_service import HiveService, HiveCredentials
from config import HIVE_GRAPHQL_URL

sys.path.insert(0, str(SHARED_CONFIG_DIR))
from config_reader import MasterConfig


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

    print(f"Querying GraphQL schema at {HIVE_GRAPHQL_URL}...\n")

    # Introspection query — get all Query and Mutation fields
    introspection_query = """
    {
      __schema {
        queryType {
          fields {
            name
            description
            args {
              name
              type {
                name
                kind
                ofType { name kind }
              }
            }
            type {
              name
              kind
              ofType { name kind }
            }
          }
        }
        mutationType {
          fields {
            name
            description
            args {
              name
              type {
                name
                kind
                ofType { name kind }
              }
            }
            type {
              name
              kind
              ofType { name kind }
            }
          }
        }
      }
    }
    """

    result = hive._execute_query(introspection_query)
    schema = result.get("__schema", {})

    # Keywords to highlight
    keywords = {"time", "timesheet", "csv", "export", "widget", "report", "tracking"}

    for section_name, section_key in [("QUERIES", "queryType"), ("MUTATIONS", "mutationType")]:
        type_obj = schema.get(section_key)
        if not type_obj:
            continue

        fields = type_obj.get("fields", [])
        print(f"{'=' * 70}")
        print(f"  {section_name} ({len(fields)} total)")
        print(f"{'=' * 70}")

        # Split into matching and non-matching
        matching = []
        others = []
        for f in fields:
            name_lower = f["name"].lower()
            desc_lower = (f.get("description") or "").lower()
            if any(kw in name_lower or kw in desc_lower for kw in keywords):
                matching.append(f)
            else:
                others.append(f)

        if matching:
            print(f"\n  --- MATCHING (timesheet/csv/export/widget/report/tracking) ---")
            for f in sorted(matching, key=lambda x: x["name"]):
                print(f"\n  >> {f['name']}")
                if f.get("description"):
                    print(f"     Description: {f['description']}")
                ret = f.get("type", {})
                ret_name = ret.get("name") or (ret.get("ofType", {}) or {}).get("name", "")
                print(f"     Returns: {ret_name} ({ret.get('kind', '')})")
                args = f.get("args", [])
                if args:
                    print(f"     Args:")
                    for a in args:
                        atype = a.get("type", {})
                        type_name = atype.get("name") or (atype.get("ofType", {}) or {}).get("name", "")
                        required = "!" if atype.get("kind") == "NON_NULL" else ""
                        print(f"       - {a['name']}: {type_name}{required}")

        print(f"\n  --- ALL OTHER {section_name} ---")
        for f in sorted(others, key=lambda x: x["name"]):
            print(f"  {f['name']}")

    # Save full introspection to file for reference
    output_path = Path(__file__).parent.parent / "output" / "schema_introspection.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as fp:
        json.dump(result, fp, indent=2)
    print(f"\nFull schema saved to: {output_path}")


if __name__ == "__main__":
    main()
