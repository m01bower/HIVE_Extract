# APP_IDENTITY.md — HIVE_Extract

Single source of truth for this app's row in `/media/michael/EXT/Projects/APP_REGISTRY.md`.
Update **both** files in the same change set when any field below changes.

Last verified: 2026-05-13

---

## Identity

| Field | Value |
|---|---|
| App ID | `HIVE_Extract` |
| Repo | `m01bower/HIVE_Extract` (GitHub, private) |
| Local path | `/media/michael/EXT/Projects/HIVE_Extract` |
| Server path | Launched by ClientPortal as subprocess from `/opt/HIVE_Extract` |
| Human name | "HIVE Extract" (portal label: "HIVE Extract") |
| Status | Live (CLI + portal-launched subprocess) |
| 24/7 service? | No — exits after each run |

## Architecture role

Sole owner of the Hive API in the BosOpt stack. Extracts project + time-tracking data from Hive (REST + GraphQL) and writes to a per-client Google Sheets workbook ("HIVE Data Sets"). Currently used only by LSC; SA/DWD design generalizes to other clients but no other clients have Hive yet.

Two job kinds in one binary:
- `mode=all` — projects + time entries + optional All-tab refresh
- `mode=projects` — projects only (no time data)

Standalone subprocess pattern: `python src/main.py` runs, writes, exits. The ClientPortal launches it via `subprocess.Popen` with `--client LSC --json --all-tab=prod` and reads the `---JSON_RESULT---` marker for structured output.

## OAuth / auth pattern

**Service-account first, OAuth fallback.** Decision tree (lives in `_shared_config/integrations/sa_policy.py::prefer_oauth_for`):

1. SA `bosopt-automations@<bosopt-gcp-project>.iam.gserviceaccount.com` is loaded from `_shared_config/clients/BosOpt/` (the SA key is BosOpt-owned, not LSC-owned).
2. If `MasterConfig` has `sa_email_impersonation` set for the client (e.g. ELW/BHCP have `finance@…` style impersonation targets), the SA assumes that identity via DWD.
3. If the client is in `sa_policy.SA_APPROVED_CLIENTS`, the SA accesses the sheet via direct share (no DWD needed). **LSC uses this path today** — the SA is shared on each target sheet directly.
4. If neither applies, the code falls back to user OAuth (BosOpt credentials). This is the safety net for clients not yet migrated.

Hive API authentication is a single API key in OS keyring under `BosOpt / Hive-APIKey` — applies to every `--client` (the API key is BosOpt's, not the client's). Client identity is conveyed to Hive via the `user_id` and `workspace_id` from MasterConfig, sent as headers.

## Tenant resolution

By `--client <key>` CLI flag. Defaults to `LSC` (the only currently active Hive client). The key is used to:

1. Load `client_config = MasterConfig().get_client(client_key)`.
2. Get `client_config.hive.workspace_id` and `client_config.hive.user_id` for Hive API calls.
3. Get `client_config.sheets.hive_extract_sheet_id` for the target spreadsheet.
4. Get `client_config.client.sa_email_impersonation` for DWD (if any).
5. Get `client_config.notifications.google_chat_webhook` for notifications.

No per-tenant code paths — all tenant-specific behavior is data-driven from MasterConfig.

## Callback / redirect pattern

None. This is a one-shot CLI; no HTTP server, no OAuth user flow, no callbacks. The OAuth fallback path uses pre-issued tokens (no interactive prompts on server).

## Primary config sources

**ALL secrets live in OS keyring.** No JSON credential files on disk. A nightly cron on the EXT drive wipes `*.json` under `_shared_config/clients/` and `_shared_config/qbo_tokens/`, so any code path that depends on a file will be broken by morning.

| Source | What lives there | Notes |
|---|---|---|
| OS keyring `BosOpt / Hive-APIKey` | Hive API key | The only Hive-specific secret. Same key for every `--client`. |
| OS keyring `MasterConfig / BosOpt_service_account_json` | SA private key JSON (whole file content as one keyring value) | Loaded via `service_account.Credentials.from_service_account_info()` — no tempfile needed; the Google library accepts dict. |
| OS keyring `MasterConfig / BosOpt_oauth_client_json` | OAuth client config (client_id, client_secret, redirect URIs) — used for the BosOpt OAuth fallback path | Rarely used (only when SA + DWD + SA-direct all fail). |
| OS keyring `MasterConfig / BosOpt_oauth_token_json` | OAuth refresh + access token for the BosOpt user | Loaded via `Credentials.from_authorized_user_info()`. On refresh, the helper writes the updated token JSON back to keyring; **never to a file**. |
| OS keyring `MasterConfig / {client}_<...>` | Auto-digested per-client secrets (Slack tokens, Chat webhooks, etc.) | Standard `{ClientName}_{field}` naming per STD-017. |
| MasterConfig sheet | Per-client non-secret config: workspace_id, user_id, sheet IDs, webhook URLs (non-secret bits), sa_email_impersonation | Read via `_shared_config/config_reader.py`. |
| `src/config.py` | `EXTRACTS`, `TABS`, `COLUMN_ORDER`, `EXCLUDED_PROJECTS_*`, `CHECKS_TAB`, Hive API URLs | Code — not config. |
| `src/settings.py` | Path helpers for `_shared_config/`, keyring access for Hive API key | Code. |

**No `config/` directory in this repo. No JSON credential files anywhere — including `_shared_config/clients/{Client}/{credentials,token,service_account}.json`.** All BosOpt-wide per STD-017. The desktop keyring AND the server keyring both hold the canonical values; the server's hourly `/opt/backups/backup-keyring.sh` cron is the durable backup. Any JSON credential file that appears on disk is treated as a leak and wiped by the EXT nightly cron.

## Schemas and contracts

Three contracts other code depends on:

1. **`MonthEXACT_RAW` tab schema** — column order frozen by `COLUMN_ORDER["time_tracking"]` in `src/config.py`. LSC_PrepTimesheets and WeeklyClientReview parse this sheet by header name. **Cross-app coupling — see `../APP_REGISTRY.md`.**
2. **`All` tab schema** — column order frozen by `COLUMN_ORDER["all_enriched"]` in `src/config.py`. AA/AB are intentional blank gap columns; AC/AD are sheet-side formula columns. Reordering breaks downstream formulas. Documented in the `COLUMN_ORDER["all_enriched"]` comment.
3. **Portal JSON contract** — when invoked with `--json`, prints `---JSON_RESULT---` then a JSON object with `status`, `results`, `checks`, `consistency`, `mode`, `all_tab`, `from_date`, `to_date`, etc. Schema documented in `docs/PRDSPDUX.md` → "Integrations → Portal JSON contract".

## Similar apps not to confuse with

- **LSC_PrepTimesheets** (port 5011) — Flask UI for timesheet approval. *Reads* `MonthEXACT_RAW` that HIVE_Extract writes. Does NOT call Hive. Different repo.
- **WeeklyClientReview** (WCR, portal key `prep_weekly_review`) — Builds monthly client-hours sheets. *Reads* HIVE-written sheets. Used to chain into HIVE_Extract's portal API; chain RETIRED 2026-05-12. WCR no longer triggers HIVE.
- **Marketing_Extract** — Different APIs (GA4/MailChimp/GSC/YouTube), different client (ELW), different auth (two-credential split). Same "extract → Sheets" pattern but no shared code beyond `_shared_config/integrations/sheets_service.py`.
- **ClientPortal `/tools/hive-extract/*`** — The portal blueprint wraps this CLI; it is *not* a second implementation. Portal route file should be ~200 lines: build_cmd, parse_output, routes. All extraction logic stays here in HIVE_Extract.

## Open-question caveats

- Three copies of `hive_service.py` historically existed across projects (LSC_PrepTimesheets, WCR, HIVE_Extract). HIVE_Extract is the canonical home; sibling copies should be removed if still present. Cross-check before assuming any specific behavior.
- Yearly tabs (`ALL_2020..ALL_2026`) are NOT written by code today — they are pasted manually by the user. The `--all-tab=prod` flow replaces the live `All` tab's LET formula but does not yet write the yearly tabs. Tracked in `docs/PRDSPDUX.md` → "Open questions".

## Verification

Status: **Verified 2026-05-13** against `src/main.py` (post-mode-collapse) and `src/config.py`. APP_REGISTRY row reviewed and consistent.

If a row in `APP_REGISTRY.md` disagrees with this file, this file is authoritative until proven otherwise.
