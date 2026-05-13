# CLAUDE.md — HIVE_Extract

This file is the entry-point memory for Claude when working in this repo.
The parent `/media/michael/EXT/Projects/CLAUDE.md` defines BosOpt-wide standards.
This file adds repo-specific guardrails on top.

---

## Doc index — where to look for specific details

**Use this first.** This file is auto-loaded every session, so these lookups cost zero context. Read leaf files surgically with `Read offset=N limit=M`, or grep for a stable ID (e.g. `grep -n "AUTH-002" docs/PRDSPDUX.md`).

| Need | File | Section / ID |
|---|---|---|
| Modes (`all`, `projects`) — what each writes | `docs/QUICK_REF.md` | "CLI modes" + FLOW-001, FLOW-002 |
| `--all-tab={skip,test,prod}` semantics | `docs/PRDSPDUX.md` | FLOW-003 |
| Single-fetch dual-write architecture (post-2026-05-13) | `docs/PRDSPDUX.md` | "Architecture" + DEC-002 |
| Two-pass GraphQL (active + archived) | `docs/PRDSPDUX.md` | RULE-004, DEC-003 |
| Output tab names + row layout (header row 4, data row 5) | `docs/QUICK_REF.md` | "Output tabs" + SCHEMA-001..005 |
| Column ordering rules (`COLUMN_ORDER`) | `src/config.py` | `COLUMN_ORDER` dict |
| Excluded projects (template hiding) | `src/config.py` | `EXCLUDED_PROJECTS_*` (RULE-009) |
| Date filtering & default range (today − 45 days) | `docs/PRDSPDUX.md` | RULE-001, RULE-002, RULE-003 |
| Pre-write project sanity check | `docs/PRDSPDUX.md` | FLOW-004 + RULE-007 |
| Consistency check (raw vs aggregated) | `docs/PRDSPDUX.md` | FLOW-005 + RULE-008 |
| Auth: SA, DWD impersonation, SA-direct, OAuth fallback | `docs/PRDSPDUX.md` | AUTH-001..005 (also `APP_IDENTITY.md` "OAuth / auth pattern") |
| Hive API key location (keyring) | `docs/PRDSPDUX.md` | AUTH-005 |
| Tenant resolution (`--client LSC`) | `docs/PRDSPDUX.md` | TEN-001..004 (also `APP_IDENTITY.md` "Tenant resolution") |
| Keyring keys + MasterConfig fields | `docs/QUICK_REF.md` | "Auth & config" |
| Portal `/api/run` payload (called by ClientPortal) | `docs/QUICK_REF.md` | "Portal call" |
| Portal JSON contract (`---JSON_RESULT---`) | `docs/PRDSPDUX.md` | API-001 |
| Integrations list (Hive REST/GraphQL, Sheets, Chat, portal, scheduler) | `docs/PRDSPDUX.md` | INT-001..008 |
| Architectural decisions (why X is the way it is) | `docs/PRDSPDUX.md` | DEC-001..009 |
| Cross-app dependents (LSC_PrepTimesheets, WCR read our sheets) | `../APP_REGISTRY.md` | HIVE_Extract row + Cross-app section |
| Open issues (Michael Cole gap, yearly tabs, hive_service copies) | `docs/PRDSPDUX.md` | OPEN-001..006 |
| 2026-04-22 Hive API discrepancy incident | `hive_api_data_discrepancy_report.md` | (whole file) |
| Historical / pre-collapse docs | `_archive/` | (preserved for reference, not current) |

When in doubt: start at `docs/QUICK_REF.md` (~130 lines, the cheat sheet). It answers most "how do I…" or "where is…" questions. Only escalate to `PRDSPDUX.md` for behavior depth — and then grep for the ID rather than reading the whole file.

## Global architecture references

This app inherits and may override BosOpt-wide rules:

| Global source | Scope | Notable rules touching HIVE_Extract |
|---|---|---|
| `/media/michael/EXT/Projects/CLAUDE.md` | Production architecture mandate (NO ERRORS REACH CLIENTS, SECURITY #1, no idle services, architecture-first) | All apply. Especially: standalone subprocess pattern (HIVE_Extract is the canonical example), keyring-only secrets, no local `config/` directory. |
| `/media/michael/EXT/Projects/APP_REGISTRY.md` | Cross-app dependency map | HIVE_Extract is the sole owner of the Hive API surface (DEC-001). Two sibling apps (LSC_PrepTimesheets, WCR) read our written sheets. |
| BosOpt MEMORY.md index | Cross-app standards (auto-loaded) | `feedback_chain_tools_via_portal_api.md` (DEC-001 derives from this), `feedback_never_pass_scopes_token_load.md` (AUTH-001..005 honor this), `feedback_no_production_writes.md` (Testing methodology honors this). |

`APP_IDENTITY.md` is authoritative for app-specific behavior. **If a global rule and `APP_IDENTITY.md` disagree, flag the conflict — do not silently resolve.** Either:
1. The app has a documented carve-out (state it in the response and quote `APP_IDENTITY.md`), or
2. The global rule was updated and `APP_IDENTITY.md` is stale (stop, ask, then update both in the same change set).

## Cross-app pattern propagation

If a change you're making here looks reusable across sibling apps (e.g. "this pattern would also work in Marketing_Extract"), **do not auto-apply it elsewhere**. Sibling apps have their own `APP_IDENTITY.md` contracts and may have reasons the pattern doesn't fit.

Instead: add a proposed entry under `/media/michael/EXT/Projects/APP_REGISTRY.md` → "Proposed cross-app pattern migrations" and surface it to the user as a follow-up question, not a silent change.

---

## Source-of-truth rules

- `APP_IDENTITY.md` — app identity contract. Read before changes involving OAuth, auth, tenant resolution, routing, config, schema boundaries, or cross-app architecture.
- `docs/PRDSPDUX.md` — canonical PRD / SPD / UX / workflows / rules / schemas / tests / decisions. Update it in the same commit as any feature, schema, UX, rule, permission, integration, or testing-behavior change. Memory notes do not substitute.
- `docs/QUICK_REF.md` — dense cheat sheet derived from PRDSPDUX. When PRDSPDUX changes meaningfully, refresh QUICK_REF in the same commit.
- The parent `CLAUDE.md` + BosOpt `MEMORY.md` index supply cross-app standards. When repo docs and memory disagree, repo docs win for this repo unless the memory was written more recently and explicitly overrides.
- **Read only the docs relevant to the change at hand.** Do not re-read the full doc set on every turn — use the doc index above.

## Mandatory app identity check

Before making or recommending changes involving auth, tenant resolution, routing, environment config, API boundaries, schemas, UX flows, or cross-app architecture, **first read `APP_IDENTITY.md`**, then state:

1. Current app ID
2. Current repo
3. Architecture role
4. OAuth / auth pattern
5. Tenant resolution pattern
6. Similar apps this must not be confused with

If any of these are unclear, **stop and ask** before editing.

## Quote-the-contract rule

Before touching auth, tenant resolution, app routing, environment config, schema boundaries, or cross-app architecture code, **quote the relevant `APP_IDENTITY.md` section you are relying on** in your response. If no section applies, stop and ask.

## OAuth / auth safety rules

This app uses **service-account auth via the `bosopt-automations` SA** with optional DWD impersonation, plus a Hive API key in keyring. Never copy auth assumptions from a sibling app — verify against `APP_IDENTITY.md`.

- Never call `Credentials.from_authorized_user_file(path, scopes)` with a scopes argument — passing scopes strips other apps' authorities from the shared token (standing BosOpt rule; see memory `feedback_never_pass_scopes_token_load.md`).
- The Hive API key lives in OS keyring under `BosOpt / Hive-APIKey` — never in config files.
- LSC is the only current `--client` value. Other clients ignored until added to `bosopt-automations` SA approval policy.
- See `APP_IDENTITY.md` for the SA / DWD / OAuth-fallback decision tree (handled by `_shared_config/integrations/sa_policy.prefer_oauth_for()`).

## Cross-app safety

Two downstream apps consume HIVE_Extract output by reading the sheets we write:

- **LSC_PrepTimesheets** reads `MonthEXACT_RAW`.
- **WeeklyClientReview** reads `MonthEXACT_RAW` (+ `Client Review Hours` derived from it).

Changes to the schema of `MonthEXACT_RAW` (column order, headers, date format) MUST be communicated as cross-app changes. See `../APP_REGISTRY.md` for the canonical map.

The portal subprocess-launches this tool via `--client LSC --json` and reads `---JSON_RESULT---`. Never break the JSON contract without updating ClientPortal in the same commit.

## PRDSPDUX update rule

`docs/PRDSPDUX.md` is the canonical project source of truth. Whenever any entity, component, rule, flow, UX, schema, permission, integration, or testing behavior changes, update `docs/PRDSPDUX.md` in the same branch/commit as the implementation. Memory notes don't substitute (standing BosOpt rule; see `feedback_features_in_prd.md`).

## Testing expectations

- `tests/` contains comparison / validation scripts (`compare_test.py`, `compare_csv_endpoint.py`, `test_two_pass_archived.py`, `test_multi_year_gap.py`, etc.). These are integration-style — they hit real Hive and real Sheets. Run them on demand, not in CI.
- Per the BosOpt-wide rule **"No Production Writes During Testing"**, never write to the production LSC Hive Data Sets sheet during test runs. Use `--client` with a non-prod config row, or `--no-sheets --excel` to write locally only.

## No secret handling

- Hive API key in keyring (`BosOpt / Hive-APIKey`); never in files.
- All other config (workspace_id, user_id, sheet IDs, webhook URLs) is in MasterConfig — non-secret, read via `_shared_config/config_reader.py`.
- `_shared_config/apps/HIVE_Extract/settings.json` may hold non-secret runtime preferences; never secrets.

## Repo conventions

- Standalone subprocess: `python src/main.py [mode] [flags]`. Exits when done; no long-running process.
- `--json` flag emits a `---JSON_RESULT---` marker followed by structured JSON for portal / scheduler consumption. Schema documented in `docs/PRDSPDUX.md` → "Integrations → Portal JSON contract".
- Dual-OS venvs (`venv-win/`, `venv-linux/`) per the BosOpt template.
- No `config/` directory in this repo. All shared config under `_shared_config/`.
- `_archive/` holds superseded docs (PROJECT_BRIEF, original spec) — historical reference only, not current state.
