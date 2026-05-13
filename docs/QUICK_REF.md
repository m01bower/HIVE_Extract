# HIVE_Extract — Quick Reference

**Last verified:** 2026-05-13 · **Current modes:** `all`, `projects` (collapsed from 4 on 2026-05-13 — DEC-005)

Single dense page covering the questions asked 80% of the time. Each fact below cites the canonical ID in `docs/PRDSPDUX.md` — grep that ID for the authoritative version. Escalate to `PRDSPDUX.md` for behavior depth.

---

## CLI modes (FLOW-001, FLOW-002)

| Mode | Hits Hive for | Writes tabs (mode-only) | Reads date range? |
|---|---|---|---|
| `all` (FLOW-001) | Projects (active+archived) + Time entries | `BillingProject_RAW`, `BillingProject_RAW_Archive`, `Projects_ALL`, `MonthEXACT_RAW` | Yes — applied to `MonthEXACT_RAW` slice only |
| `projects` (FLOW-002) | Projects (active+archived) | `BillingProject_RAW`, `BillingProject_RAW_Archive`, `Projects_ALL` | No — projects ignore date range |

Retired 2026-05-13 (DEC-005): `monthexact`, `hive_report`. Their work is folded into `all` + `--all-tab=prod`.

## `--all-tab` flag (mode=all only) — FLOW-003

| Value | Behavior | When |
|---|---|---|
| `skip` | Don't touch the All tab | local CLI default (DEC-006) |
| `test` | Write enriched aggregation to `All_TEST` | parity check during rollout |
| `prod` | Overwrite live `All!A4:AZ50000` (replaces legacy LET formula — DEC-004) | **portal always passes this** (DEC-006) |

When `test` or `prod`, the time-entry fetch widens to `2020-01-01..today` (RULE-003) so `MonthEXACT_RAW` and `All` come from the same in-memory data — **single-fetch dual-write (DEC-002), 0.00h drift target enforced at runtime by FLOW-005**.

## Output tabs (LSC "HIVE Data Sets" sheet) — SCHEMA-001..005

| Tab | ID | Source | Row layout |
|---|---|---|---|
| `BillingProject_RAW` | SCHEMA-001 | Active projects (REST GraphQL `archived:false`) | Header row 4, data row 5+ |
| `BillingProject_RAW_Archive` | SCHEMA-002 | Archived projects (`archived:true`) — live archive, not a backup | Header row 4, data row 5+ |
| `Projects_ALL` | SCHEMA-003 | Active + Archived concatenated in memory | Header row 4, data row 5+ |
| `MonthEXACT_RAW` | SCHEMA-004 | Time entries within `--from-date..--to-date` (default 45d) | Header row 4, data row 5+ |
| `All` | SCHEMA-005 | Enriched monthly aggregation (only with `--all-tab=prod`) | Header row 4, data row 5+, code clears `A4:AZ50000` (DEC-004) |
| `All_TEST` | SCHEMA-005 (target variant) | Same as `All` but for parity-check (only with `--all-tab=test`) | Header row 4, data row 5+ |
| `Month` | — | =FILTER(All!…) sheet-side formula — **never written by code** | — |
| `ALL_YYYY` (2020..2026) | — | Pasted manually by user today — **not written by code** (DEC-007, OPEN-001) | Header row 5, data row 6+ |
| `Checks` | — | Read-only validation (formula sheet) | A3 = summary cell, A4:D20 = per-tab detail |

Rows 1–3 on every code-written tab are reserved for sheet-side formulas — never touched (RULE-005).

## CLI flags (full)

```
python src/main.py [mode] [options]

mode: all | projects  (default: all)

--setup                 Run setup wizard (configure Hive API key)
--from-date YYYY-MM-DD  Start date (default: today − 45 days)
--to-date   YYYY-MM-DD  End date   (default: today)
--client KEY            MasterConfig client key (default: LSC)
--no-sheets             Skip Google Sheets; write Excel only
--excel                 Also write Excel files (default: Sheets only)
--all-tab {skip,test,prod}   Control the All tab write (mode=all only)
--json                  Emit ---JSON_RESULT--- + JSON for portal/scheduler
```

Date defaults: today − 45 days through today. The `--all-tab≠skip` fetch widens to 2020-01-01..today regardless of `--from-date`.

## Auth & config — AUTH-001..005, TEN-001..004

| Where | What | ID |
|---|---|---|
| OS keyring `BosOpt / Hive-APIKey` | **Hive API key** (only secret) | AUTH-005 |
| OS keyring `MasterConfig / LSC_…` | Per-client secrets auto-digested from MasterConfig | — |
| MasterConfig "Hive" tab | `workspace_id`, `user_id` per client | TEN-001 |
| MasterConfig "Sheets" tab | `hive_extract_sheet_id` per client | TEN-002 |
| MasterConfig "Notifications" tab | `google_chat_webhook` per client | INT-005 |
| MasterConfig "Clients" tab | `sa_email_impersonation` (DWD target if any) | AUTH-002 |
| OS keyring `MasterConfig / BosOpt_service_account_json` | SA private key JSON (whole file as one keyring value; `from_service_account_info(dict)`) | AUTH-001 |
| OS keyring `MasterConfig / BosOpt_oauth_client_json` | OAuth client config (OAuth fallback only) | AUTH-004 |
| OS keyring `MasterConfig / BosOpt_oauth_token_json` | OAuth refresh+access token (OAuth fallback only; refresh writes back to keyring, never to disk) | AUTH-004 |
| `_shared_config/apps/HIVE_Extract/settings.json` | Non-secret app prefs | — |

**SA / DWD / OAuth decision lives in** `_shared_config/integrations/sa_policy.py::prefer_oauth_for()`. LSC = SA direct-share (AUTH-003 — in `SA_APPROVED_CLIENTS`), no DWD impersonation.

## Portal call (ClientPortal → HIVE_Extract)

Subprocess.Popen launch from ClientPortal:
```
python /opt/HIVE_Extract/src/main.py all \
  --client LSC --json --all-tab=prod
```

Portal endpoint: `POST /tools/hive-extract/api/run` on `lsc.bosoptimization.com`
- Headers: `X-API-Key: <Portal-APIKey>`, `Host: lsc.bosoptimization.com`
- Body: `{}` (params optional)
- Response: `202 {"job_id": "..."}` → poll `/api/job/<id>` for status

JSON contract from CLI (post `---JSON_RESULT---` marker):
```json
{
  "status": "success" | "partial",
  "results": { "<filename>": { "description": "...", "status": "...", "rows": N, "time": s, "error": null|str } },
  "checks": "ALL GOOD" | "<problem>",
  "checks_ok": bool,
  "checks_detail": [{ "tab": "...", "updated": "...", "error1": "...", "error2": "...", "is_error": bool }],
  "consistency": { "ok": bool, "daily_hours": h, "enriched_hours": h, "drift_hours": h, ... } | null,
  "total_rows": N, "success_count": N, "error_count": N, "elapsed": s,
  "mode": "all" | "projects", "all_tab": "skip" | "test" | "prod",
  "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD"
}
```

## Source-of-truth files

| Path | Owns |
|---|---|
| `src/main.py` | Mode dispatch, orchestration, consistency check, All-tab write |
| `src/services/hive_service.py` | All Hive API calls — REST + GraphQL, two-pass archived fetch, enrichment |
| `src/services/sheets_service.py` | Wrapper around `_shared_config/integrations/sheets_service.py` |
| `src/config.py` | `EXTRACTS`, `TABS`, `COLUMN_ORDER`, `EXCLUDED_PROJECTS_*`, `CHECKS_TAB`, Hive URLs |
| `src/settings.py` | Keyring access, `_shared_config/` path helpers |
| `src/notification.py` | Google Chat post-run webhook |

## Known gotchas (4)

1. **Two-pass archived fetch** (RULE-004, DEC-003). Hive's GraphQL with `archived:null` returns inconsistent results — code does two explicit passes (`archived:false` then `archived:true`) and concatenates. Fixed 2026-04-22; closed the prior Michael Cole gap (OPEN-002 resolved 2026-05-13).
2. **`Month` tab is a formula, not code-written.** `=FILTER(All!A5:Z, ...)` — refreshes automatically when `All` changes. Do not write to `Month` from code.
3. **`ALL_YYYY` tabs are retired** (DEC-007, OPEN-001 resolved 2026-05-13). The All-tab redesign (DEC-002) owns yearly aggregation; legacy yearly tabs are hidden in the sheet pending deletion. Code does not write them and the user no longer pastes them.
4. **`Checks` tab read with 30s delay** (DEC-009). Sheets needs time to recalc after bulk writes. The `time.sleep(30)` before reading `Checks!A3` is intentional — don't shorten it.

## Run on server

ClientPortal launches via subprocess. To run manually on Hetzner (rare):
```
cd /opt/HIVE_Extract && venv-linux/bin/python src/main.py all --client LSC --all-tab=prod
```
Logs: project-local `logs/hive_extract_YYYY-MM-DD.log` (daily rotating).

## Run locally (dev)

```
cd /media/michael/EXT/Projects/HIVE_Extract
./run.sh                 # default: all modes, last 45d, Sheets on
./run.sh projects        # projects only
./run.sh all --all-tab=test --no-sheets --excel   # safe dry run
```
