# PRDSPDUX.md — HIVE_Extract

Canonical project source of truth for PRD, SPD, UX, workflows, rules, schemas, tests, integrations, and major decisions.

> Whenever any entity, component, rule, flow, UX, schema, permission, integration, or testing behavior changes, **update this file in the same branch/commit as the implementation**. Memory notes do not substitute.

## Stable ID scheme

Important items below carry a stable ID (e.g. `AUTH-001`, `FLOW-002`, `RULE-005`) so other docs can reference them without depending on line numbers. **IDs are content-anchored — they survive reorderings, line drift, and section renames.** Grep for the ID to jump to the definition.

Prefixes used in this file: `AUTH`, `TEN`, `FLOW`, `RULE`, `CFG`, `INT`, `API`, `DEC`, `SCHEMA`, `OPEN`. Each ID is defined exactly once; sibling docs (`CLAUDE.md`, `QUICK_REF.md`) cite IDs to point at canonical definitions.

**When you change an ID'd item:** keep the ID. Only retire an ID (mark as `DEC-005 (retired)` etc.) — never reuse it for unrelated content, and never silently renumber.

```yaml
app: HIVE_Extract
status: live (CLI + portal-launched subprocess)
version_marker: 2026-05-13 mode collapse + all-tab cutover
clients_in_use: [LSC]
ports: []  # no HTTP server
service_unit: none  # subprocess-only
db: none  # state lives in target Sheet
auth: SA bosopt-automations (SA-direct for LSC; OAuth fallback)
hive_api_key_location: keyring BosOpt/Hive-APIKey
tenant_resolution: --client CLI flag (default LSC)
job_kinds: [mode=all, mode=projects]
canonical_tabs: [BillingProject_RAW, BillingProject_RAW_Archive, Projects_ALL, MonthEXACT_RAW, All]
formula_tabs: [Month, Checks]              # never written by code
manual_tabs: [ALL_2020, ..., ALL_2026]     # pasted manually today
```

---

## Contents

| Section | Lines | Primary IDs defined |
|---|---|---|
| 1. Product overview | 58 – 72 | — |
| 2. Architecture summary | 73 – 129 | — |
| 3. App role in the multi-app system | 130 – 147 | — |
| 4. Entities and schemas | 148 – 182 | SCHEMA-001..005 |
| 5. Workflows | 183 – 245 | FLOW-001..005 |
| 6. UX flows (CLI + portal) | 246 – 275 | — |
| 7. Business rules | 276 – 287 | RULE-001..009 |
| 8. Permissions and tenant rules | 288 – 294 | TEN-001..004 |
| 9. Auth flow (SA / DWD / OAuth) | 295 – 304 | AUTH-001..005 |
| 10. Integrations | 305 – 354 | INT-001..008, API-001 |
| 11. Testing methodology | 355 – 372 | — |
| 12. Current decisions | 373 – 386 | DEC-001..009 |
| 13. Open questions | 387 – 395 | OPEN-001..007 |

**To find an ID:** `grep -n "AUTH-002" docs/PRDSPDUX.md` (or whichever ID) gives the line; then `Read offset=N limit=10`. IDs survive line drift; the line-range column is for whole-section reads.

When you need a section, `Read offset=<start> limit=<end−start+1>` rather than reading the whole file.

---

## 1. Product overview

HIVE_Extract automates the export of project management and time tracking data from Hive (hive.com) into a Google Sheets workbook. Built for Lydia Sierra Consulting (LSC); currently the only active Hive client. Replaces a manual 3x/week CSV-download-and-paste process.

**Goals:**
- Replace manual UI exports with deterministic API-driven writes.
- Guarantee that the monthly `All` tab and the `MonthEXACT_RAW` slice never disagree (same in-memory pull, 0.00h drift target).
- Be the **sole owner of the Hive API** across BosOpt — any other app needing Hive data reads the sheets HIVE_Extract writes, never calls Hive directly.
- Run idempotently — re-running with the same inputs produces the same outputs and overwrites in place (rows 4+) without disturbing sheet-side formulas (rows 1–3).

**Non-goals:**
- Not a real-time sync. Each run is a snapshot; "current data" means "as of last run".
- Not multi-tenant in the UI sense — the CLI takes `--client` and that's the whole tenant model.
- Not a 24/7 service. CLI runs, writes, exits.

## 2. Architecture summary

```
┌────────────────────────────┐
│  CLI: python src/main.py   │
│  args: mode, --all-tab,    │
│         --from-date,       │
│         --to-date,         │
│         --client, --json   │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────────────────────────┐
│  run_extracts(mode, all_tab, ...)              │
│                                                │
│  1. Load API key (keyring) + MasterConfig      │
│  2. Connect Hive + Google Sheets               │
│                                                │
│  ┌─ PROJECTS (both modes) ─────────────────┐   │
│  │ hive.get_projects(archived=False) ─────▶│   │ active
│  │ hive.get_projects(archived=True)  ─────▶│   │ archived  (two-pass)
│  │                                         │   │
│  │ pre_write_project_check (rows + $$)     │   │
│  │ Write: BillingProject_RAW, _Archive,    │   │
│  │        Projects_ALL                     │   │
│  └─────────────────────────────────────────┘   │
│                                                │
│  ┌─ TIME (mode=all only) ──────────────────┐   │
│  │ all_daily_entries = hive.get_time_      │   │
│  │     entries(fetch_from, fetch_to)       │   │
│  │ fetch_from = 2020-01-01 if all_tab≠skip │   │
│  │              else --from-date           │   │
│  │                                         │   │
│  │ MonthEXACT_RAW = slice [from..to]       │   │
│  │ Write: MonthEXACT_RAW                   │   │
│  │                                         │   │
│  │ if all_tab in (test, prod):             │   │
│  │   enriched = hive.get_enriched_         │   │
│  │       monthly_entries(daily, active,    │   │
│  │       archived)                         │   │
│  │   _consistency_check(daily, enriched)   │   │
│  │   _write_all_tab(enriched, all|All_TEST)│   │
│  └─────────────────────────────────────────┘   │
│                                                │
│  3. sleep 30s; read Checks!A3 + detail         │
│  4. Send Google Chat notification              │
│  5. Print ---JSON_RESULT--- if --json          │
└────────────────────────────────────────────────┘
```

**Key insight — single-fetch dual-write (post-2026-05-13):** when `--all-tab≠skip`, the time-entry GraphQL call returns the full history once. `MonthEXACT_RAW` is just a slice of that in-memory list; `All` is the enriched aggregation of that same list. They cannot drift because they come from the same Python object — verified at runtime by `_consistency_check` (drift target < 0.02h).

**Hive API surface used:**
- REST `app.hive.com/api/v1/projects` — projects (active + archived passes).
- GraphQL `prod-gql.hive.com/graphql` — `getTimeTrackingData` for daily entries.
- GraphQL `getTimesheetReportingCsvExportData` — known-bad endpoint; do NOT use for year tabs (returned incorrect data per 2026-04-22 incident; bug reported, still unfixed as of last check).

## 3. App role in the multi-app system

| Aspect | Value |
|---|---|
| App ID | `HIVE_Extract` |
| Architecture role | **Sole owner of the Hive API.** Other BosOpt apps consume Hive data by reading the sheets HIVE_Extract writes, never by calling Hive themselves. |
| 24/7 service? | No — subprocess that exits |
| Tenant model | `--client KEY` CLI flag (default `LSC`). Used to look up workspace_id / user_id / sheet_id / SA impersonation target / webhook in MasterConfig. |
| Auth | SA `bosopt-automations` (BosOpt-owned). LSC = SA direct-share. DWD-impersonation path exists for clients with `sa_email_impersonation` in MasterConfig. OAuth fallback via BosOpt creds. |
| Launched by | (1) Direct CLI for ad-hoc / dev runs; (2) ClientPortal subprocess for portal-triggered runs; (3) Scheduler systemd timer (via ClientPortal `/api/run`) for recurring runs. |
| Reads | MasterConfig sheet, Hive REST + GraphQL APIs, target sheet (for `Checks` tab + pre-write totals). |
| Writes | 5 tabs on the target sheet (see §4). |

Cross-app consumers of HIVE_Extract output (sheet-level coupling, see `../APP_REGISTRY.md`):

- **LSC_PrepTimesheets** — reads `MonthEXACT_RAW`.
- **WeeklyClientReview** — reads `MonthEXACT_RAW` + derived `Client Review Hours`. (The reverse chain — WCR triggering HIVE_Extract — was retired 2026-05-12.)

## 4. Entities and schemas

State lives in the target Google Sheet (per-client). No local DB.

### Tabs written by code

| ID | Tab | Source extract | Column order source | Layout |
|---|---|---|---|---|
| SCHEMA-001 | `BillingProject_RAW` | `hive.get_projects(archived=False)` | `COLUMN_ORDER["active_projects"]` | Header row 4, data row 5+ |
| SCHEMA-002 | `BillingProject_RAW_Archive` | `hive.get_projects(archived=True)` | `COLUMN_ORDER["archived_projects"]` | Header row 4, data row 5+ |
| SCHEMA-003 | `Projects_ALL` | `active + archived` (in-memory concat) | `COLUMN_ORDER["all_projects"]` | Header row 4, data row 5+ |
| SCHEMA-004 | `MonthEXACT_RAW` | `hive.get_time_entries(from, to)` (slice if all_tab≠skip) | `COLUMN_ORDER["time_tracking"]` | Header row 4, data row 5+ |
| SCHEMA-005 | `All` (or `All_TEST`) | `hive.get_enriched_monthly_entries(daily, active, archived)` | `COLUMN_ORDER["all_enriched"]` | Header row 4, data row 5+, clears `A4:AZ50000` first |

### Tabs read but never written

| Tab | What it holds | Why we read |
|---|---|---|
| `Checks` | Sheet-side validation formulas. `A3` = summary cell ("ALL GOOD" / "N ERROR(S)"). `A4:D20` = per-tab detail rows. | Post-write validation reads `A3`; portal status page reads the detail range. |

### Tabs that exist but are not our responsibility

| Tab | Status |
|---|---|
| `Month` | Sheet-side `=FILTER(All!A5:Z, ...)` formula. Auto-refreshes when `All` changes. |
| `ALL_YYYY` (2020..2026) | Pasted manually by user today. Code does NOT write these. **Open question** — see §13. |

### Excluded data

| Set | Source | Why excluded |
|---|---|---|
| `EXCLUDED_PROJECTS_ACTIVE` (6 entries) | `src/config.py` | Templates ("LOI Template", "Proposal Template", etc.) that the Hive API returns but the UI hides. Excluding them makes our row count match the Hive UI export. |
| `EXCLUDED_PROJECTS_ARCHIVED` (2 entries) | `src/config.py` | Same — internal items (`Monthly Work`, `Prospect Review Template`). |
| `EXCLUDED_COLUMNS` = {"Monthly Budget"} | `src/config.py` | Never useful in our context. |

## 5. Workflows

### FLOW-001 · 5a. mode=all (full run)

1. Parse args. Set `from_date = today−45d, to_date = today` unless overridden.
2. Load Hive API key from `BosOpt/Hive-APIKey`. Test connection.
3. Load MasterConfig → ClientConfig. Open Sheets via SA (with DWD if `sa_email_impersonation` set; else SA-direct; else OAuth fallback).
4. **Projects sub-flow** (also runs in `mode=projects`):
   - Two-pass fetch: `archived=False` then `archived=True`.
   - **Pre-write check** (§5d) — compares new totals to existing sheet totals; warns if rows or $ awarded dropped.
   - Write `BillingProject_RAW`, `BillingProject_RAW_Archive`, `Projects_ALL`.
5. **Time sub-flow** (only `mode=all`):
   - Fetch range: `2020-01-01..today` if `--all-tab≠skip`, else `from_date..to_date`.
   - One GraphQL call → `all_daily_entries`.
   - Slice for `MonthEXACT_RAW`: filter to `[from_date..to_date]` (when fetch was wider) or use as-is.
   - Write `MonthEXACT_RAW`.
6. **All-tab sub-flow** (only `--all-tab in {test, prod}`):
   - `enriched = hive.get_enriched_monthly_entries(...)` — aggregates daily → monthly per (person, project), enriches with project metadata.
   - **Consistency check** (§5e) — `sum(daily) == sum(enriched)` within 0.02h. Logs `OK` or `FAIL`.
   - `_write_all_tab(enriched, "all" or "all_test")`:
     - Clear `<tab>!A4:AZ50000` (wipes legacy LET formula on the live `All` tab).
     - Write canonical headers to `A4` (RAW).
     - Write data to `A5+` (USER_ENTERED so dates parse).
     - Update timestamp `C1`.
7. Sleep 30s (Sheets recalc time).
8. Read `Checks!A3` → "ALL GOOD" or problem text. Read `Checks!A4:D20` for per-tab detail.
9. Send Google Chat notification (per-extract status + Checks summary).
10. If `--json`, print `---JSON_RESULT---` and the structured payload (see §10 for schema).

### FLOW-002 · 5b. mode=projects (projects only)

Steps 1–3 then 4 only. Exits.

### FLOW-003 · 5c. All-tab write semantics (`--all-tab`)

| Value | What changes vs skip |
|---|---|
| `skip` | Time-entry fetch is just `from_date..to_date`. `MonthEXACT_RAW` is the whole returned set. `All` tab untouched. |
| `test` | Fetch widens to `2020-01-01..today`. `MonthEXACT_RAW` is the date-sliced subset. Aggregation written to `All_TEST` tab (parity check). `All` tab untouched. |
| `prod` | Same as `test` but writes to live `All` tab. Replaces the legacy `=LET(...)` formula in `A4` with code-owned rows. |

`--all-tab` is **silently ignored** when `mode≠all` (time data is needed for aggregation). Portal always passes `--all-tab=prod`.

### FLOW-004 · 5d. Pre-write project check

Before clearing `BillingProject_RAW` / `_Archive`:
- Read existing `B2` (row count) and `N1` (`Amount Awarded` total) from each tab.
- Compute new totals from in-memory active + archived.
- If `new_total_rows < prev_total_rows`: WARN.
- If `new_total_awarded < prev_total_awarded`: WARN.
- **Warning does NOT block the write.** The check is informational; a drop is suspicious but legitimate cases exist (e.g. data correction).

### FLOW-005 · 5e. Consistency check (raw vs aggregated)

Only runs when `--all-tab≠skip`. Both sides are derived from the same in-memory `all_daily_entries`:

- `daily_total = sum(Tracked (Minutes)) / 60` (rounded to 2 decimals).
- `enriched_total = sum(Hours)` from aggregation.
- `drift = enriched_total - daily_total`.
- `ok = abs(drift) < 0.02`.

The function also computes the `MonthEXACT_RAW` slice total, this-month totals (raw vs aggregated), and this-year totals (raw vs aggregated) — purely for the human-readable log and the `consistency` block in JSON output. A `FAIL` is logged loudly but does not abort the run (the All tab still gets written; the operator sees the FAIL in chat + JSON).

## 6. UX flows (CLI + portal)

### 6a. CLI

```
$ python src/main.py all --client LSC
Client: LSC
Mode: all
All-tab: skip
Date range: 2026-03-29 to 2026-05-13

Output: Google Sheets
  BillingProject_RAW.xlsx: 47 rows (3.1s)
  BillingProject_RAW_Archive.xlsx: 198 rows (4.0s)
  Projects_ALL.xlsx: 245 rows (4.6s)
  MonthEXACT_RAW.xlsx: 4,127 rows (5.2s)

  Total: 4,617 rows, 16.9s elapsed
```

With `--json`, the same output is followed by `---JSON_RESULT---` and the structured payload.

### 6b. Portal

`POST /tools/hive-extract/api/run` on `lsc.bosoptimization.com` → `202 {"job_id"}`. Portal status page polls `/api/job/<id>` and renders per-tab status + Checks detail. Run logs available at the Activity Log page.

### 6c. Scheduler

Scheduler row points at `client_key=LSC`, `tool_key=hive_extract`. Materializes as `scheduler-job@N.timer`. Each fire POSTs to the portal endpoint above with `params={}` (the portal passes the default `--all-tab=prod` for now — see §13 if that needs to change).

## 7. Business rules

- **RULE-001 · All times in Eastern Time** (project-wide BosOpt rule). Dates from Hive are ISO strings; comparison and slicing use string compare which is safe for ISO.
- **RULE-002 · Default date range:** today − 45 days through today. Override via `--from-date` / `--to-date`.
- **RULE-003 · `--all-tab≠skip` widens the fetch** to `2020-01-01..today` regardless of `--from-date`. `MonthEXACT_RAW` is then the sliced subset.
- **RULE-004 · Two-pass archived fetch** is mandatory. Hive's GraphQL with `archived:null` returns inconsistent data (incident 2026-04-22). Always run `archived:false` and `archived:true` separately.
- **RULE-005 · Row 1–3 of every code-written tab is OFF-LIMITS.** They hold sheet-side formulas (timestamps, summary checks, the legacy LET on `All`). Code writes headers to row 4 and data to row 5+.
- **RULE-006 · All-tab clear range is `A4:AZ50000`**, not just `A4:Z`. The legacy LET spilled wide; we clear wide to be safe.
- **RULE-007 · Pre-write check is informational, not blocking.** A drop in row count or $ awarded logs a WARN but the write proceeds.
- **RULE-008 · Consistency check FAIL does not abort.** The operator sees it in chat + JSON.
- **RULE-009 · Hive UI parity is enforced by `EXCLUDED_PROJECTS_*` and `EXCLUDED_COLUMNS`** in `src/config.py`. When these lists change, the row count diff between sheet and Hive UI will change — communicate to the user.

## 8. Permissions and tenant rules

- **TEN-001 · Single Hive API key** per the BosOpt account. Same key used for every `--client` (the API key is BosOpt's; tenant identity is in `workspace_id` + `user_id` sent as headers per request).
- **TEN-002 · Per-client sheet ID** comes from MasterConfig `sheets.hive_extract_sheet_id`. Wrong client = wrong sheet, but never another tenant's data (data comes from Hive headers, sheet is just the output destination).
- **TEN-003 · SA isolation:** the `bosopt-automations` SA's access is granted explicitly per sheet (LSC direct-share today). Removing the SA from a sheet immediately blocks writes there.
- **TEN-004 · OAuth fallback** uses BosOpt's user credentials — meaning if SA fails, a BosOpt admin (Michael) effectively writes. Acceptable safety net; not a long-term path.

## 9. Auth flow (SA / DWD / OAuth)

Decision tree, implemented in `_shared_config/integrations/sa_policy.prefer_oauth_for(client_key)`. **All credential material is loaded from OS keyring, not files** (STD-017; nightly cron wipes any `*.json` under `_shared_config/clients/`).

- **AUTH-001 · SA load:** SA private key JSON read from keyring `MasterConfig / BosOpt_service_account_json`. Passed into `service_account.Credentials.from_service_account_info(json.loads(value), scopes=...)` — Google library accepts dict directly, no tempfile needed.
- **AUTH-002 · DWD impersonation path:** if `client_config.client.sa_email_impersonation` is set, the SA assumes that identity via Google Domain-Wide Delegation (`with_subject(email)` on the SA creds object). How ELW / BHCP access *their* finance@ Drive without sharing files with the SA directly. **Not used by LSC today** (LSC SA-direct).
- **AUTH-003 · SA-direct path:** if `client_key in sa_policy.SA_APPROVED_CLIENTS`, the SA accesses the target sheet via direct share (sheet's "Share" dialog includes `bosopt-automations@…`). LSC is on this list.
- **AUTH-004 · OAuth fallback:** if neither applies, falls back to user OAuth. Both the OAuth client config (`MasterConfig / BosOpt_oauth_client_json`) and the user token (`MasterConfig / BosOpt_oauth_token_json`) come from keyring. `Credentials.from_authorized_user_info(json.loads(token_value), scopes=...)`. On refresh, the helper writes the new token JSON back to keyring; **the helper never writes a file**. Last-resort path; rarely exercised.
- **AUTH-005 · Hive API key:** independent of the SA/DWD/OAuth tree above. Read `BosOpt / Hive-APIKey` from OS keyring; send as `Authorization: Bearer …` (REST) or `api_key` header (GraphQL). Same key for every `--client`.

## 10. Integrations

| ID | Target | Direction | Mechanism |
|---|---|---|---|
| INT-001 | Hive REST `app.hive.com/api/v1/projects` | GET | API key in `Authorization`. Used for active + archived passes. |
| INT-002 | Hive GraphQL `prod-gql.hive.com/graphql` | POST | API key in headers + `user_id`. Used for `getTimeTrackingData`. |
| INT-003 | Hive GraphQL `getTimesheetReportingCsvExportData` | (BAD — DO NOT USE) | Returns incorrect data per 2026-04-22 incident. Bug reported, unfixed as of last check. The `year_raw` / `ALL_YYYY` workflow that depended on it is parked. |
| INT-004 | Target Google Sheet | RW | Via `_shared_config/integrations/sheets_service.py`. Auth per §9. Writes are batched. |
| INT-005 | Google Chat webhook (per-client) | POST | URL from `client_config.notifications.google_chat_webhook`. Posted at end of every run with per-extract status + Checks summary. |
| INT-006 | ClientPortal `/tools/hive-extract/*` | (consumed) | Portal route file is a thin launcher: builds the CLI command, runs as subprocess, parses `---JSON_RESULT---`. |
| INT-007 | Scheduler | (consumed) | Calls ClientPortal `/api/run` endpoint. Never calls this CLI directly. |
| INT-008 | `_shared_config/integrations/notify.py::notify_uncaught` | decorator on `main()` | Reports any uncaught exception to Google Chat + Gmail SMTP. |

### API-001 · Portal JSON contract (`---JSON_RESULT---` payload)

```json
{
  "status": "success" | "partial",
  "results": {
    "<filename>": {
      "description": "Active Projects",
      "status": "success" | "error" | "skipped",
      "rows": 47,
      "time": 3.1,
      "error": null | "..."
    }
  },
  "checks": "ALL GOOD" | "<problem text>",
  "checks_ok": true | false,
  "checks_location": "Checks!A3" | "",
  "checks_detail": [
    { "tab": "MonthEXACT_RAW", "updated": "2026-05-13 09:32 ET", "error1": "0 ERRORS", "error2": "", "is_error": false }
  ],
  "consistency": {
    "ok": true, "daily_hours": 12345.67, "enriched_hours": 12345.67,
    "drift_hours": 0.00, "monthexact_slice_hours": 1234.56,
    "monthexact_range": "2026-03-29 .. 2026-05-13",
    "this_month_raw": 234.5, "this_month_aggregated": 234.5,
    "this_year_raw": 5432.1, "this_year_aggregated": 5432.1
  },
  "total_rows": 4617, "success_count": 4, "error_count": 0,
  "elapsed": 16.9,
  "mode": "all" | "projects",
  "all_tab": "skip" | "test" | "prod",
  "from_date": "2026-03-29", "to_date": "2026-05-13"
}
```

Breaking this contract breaks ClientPortal's status page and any downstream consumer. Treat it as a public API.

## 11. Testing methodology

`tests/` holds **integration-style** scripts (not pytest-style unit tests):

| Script | Purpose |
|---|---|
| `compare_csv_endpoint.py` | Compares the (broken) CSV endpoint output against ground truth. Used during the 2026-04 incident investigation. |
| `compare_test.py` | Diff two extract runs. |
| `test_two_pass_archived.py` | Validates that `archived:false` + `archived:true` two-pass equals the UI export. The reason the two-pass exists. |
| `test_multi_year_gap.py` | Multi-year history gap check. |
| `test_include_archived_flag.py` | Behavior of the `archived` GraphQL flag. |
| `test_monthly_aggregation.py` | Aggregation drift check (this is the "raw vs enriched" equality, now also enforced at runtime by `_consistency_check`). |
| `test_csv_endpoint.py` | Raw smoke test for the CSV endpoint. |

These hit real Hive + real Sheets. Per the BosOpt-wide **"No Production Writes During Testing"** rule, run them against a non-prod `--client` config OR pair with `--no-sheets --excel` to write locally only. **Never** run against the LSC production sheet during dev.

Future work: extract aggregation logic into a pure function and pytest it offline. Tracked in §13.

## 12. Current decisions

| ID | Decision | Why |
|---|---|---|
| DEC-001 | **Sole owner of Hive API** | Single point of trust for "what does the Hive API return"; avoids drift between sibling apps reimplementing the same fetch. Tracked in memory `feedback_chain_tools_via_portal_api.md`. |
| DEC-002 | **Single-fetch dual-write** (2026-05-13) | Eliminates drift between `MonthEXACT_RAW` and `All` by deriving both from the same in-memory `all_daily_entries`. Replaced the prior split where `hive_report` mode rebuilt the All tab from a separate fetch. |
| DEC-003 | **Two-pass archived fetch** (2026-04-22) | Hive's `archived:null` returns inconsistent data. Two explicit passes match the UI export exactly. |
| DEC-004 | **All tab clear range `A4:AZ50000`** | The legacy LET formula spilled wide; clearing wide guarantees no orphan cells survive the cutover. |
| DEC-005 | **Modes collapsed to {all, projects}** (2026-05-13) | `monthexact` was a subset of `all`; `hive_report` was a special case of "fetch + aggregate" now folded into `all + --all-tab=prod`. Cleaner CLI, fewer cross-app trip-hazards. Cross-app callers (Scheduler, ClientPortal) updated in the same change set. |
| DEC-006 | **`--all-tab=skip` by default in CLI; `prod` from portal** | Local CLI use is mostly debugging where you don't want to overwrite production. Portal use is always "do the real thing". The default is explicit on the portal side. |
| DEC-007 | **No code writes to `ALL_YYYY`** | Yearly tabs depend on a known-bad Hive endpoint. User pastes manually until Hive fixes the endpoint or we re-derive from time entries. See §13. |
| DEC-008 | **`_consistency_check` non-blocking** | A FAIL is visible (log + chat + JSON) but doesn't block the write. The All tab is still useful even if drift exists; aborting on FAIL would hide *all* data, not just the drifty subset. |
| DEC-009 | **30-second sleep before reading `Checks!A3`** | Sheets recalc lag after bulk writes is real; shorter waits gave false `#REF!`/stale reads. 30s is conservative but reliable. |

## 13. Open questions

- **OPEN-001 · Yearly `ALL_YYYY` tabs.** Hive's `getTimesheetReportingCsvExportData` returns wrong data, so we cannot derive these from the CSV export. **Option A:** wait for Hive (open ticket, no progress as of last check). **Option B:** derive from `all_daily_entries` by year-bucketing — same data path as the `All` tab, just sliced differently. Option B is what the user would want; tracked in memory `hive_all_tab_redesign.md` as a follow-up to the 2026-05-13 cutover.
- **OPEN-002 · Michael Cole residual gap (−37.95 hrs).** As of 2026-04-22, after the two-pass fix, one user shows a small persistent gap vs ground truth. Escalated to Hive — likely a Hive-side data anomaly, not our extraction. Re-check periodically; close if Hive confirms.
- **OPEN-003 · Three copies of `hive_service.py`.** Historically `LSC_PrepTimesheets`, `WeeklyClientReview`, and `HIVE_Extract` each had their own copy. Per DEC-001 (sole owner), HIVE_Extract is canonical. Audit + remove sibling copies if still present. Tracked in memory `hive_extract.md`.
- **OPEN-004 · WCR retired the HIVE chain** (2026-05-12); however the `runner.py:939-943` block may still hold portal-API-key wiring even though the chain is dead. Cleanup planned. Not a blocker.
- **OPEN-005 · Promote ClientPortal's `--all-tab` choice to a portal param?** Today it's hardcoded to `prod`. If we ever want to run a `test` parity job from the portal (e.g. before a schema change), the portal route would need to accept and forward the flag. Low priority.
- **OPEN-006 · Pytest-able aggregation.** `get_enriched_monthly_entries` lives in `hive_service.py` and mixes API calls with aggregation logic. Splitting the aggregation into a pure function would let us unit-test the `_consistency_check` invariant offline. Tracked as future work.
- **OPEN-007 · Verify zero JSON credentials on disk.** After the 2026-05-13 migration (keyring is now the canonical source for all credential material — AUTH-001..005), confirm no path in HIVE_Extract or any shared module imports `credentials.json`, `token.json`, or `service_account.json` from disk. Nightly EXT cron will catch leaks; failure to load auth on a fresh clone is the symptom of an unmigrated code path. Re-verify after every release.
