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
| Open issues (resolved + current) | `docs/PRDSPDUX.md` | OPEN-001..007 |
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

Auth pattern: see `AUTH-001..005` and `APP_IDENTITY.md` → "OAuth / auth pattern". Standing global rule: never pass `scopes=` to `Credentials.from_authorized_user_file` (strips other apps' authorities from the shared token).

## Cross-app safety

Downstream consumers and schema-coupling rules: see `APP_IDENTITY.md` → "Similar apps not to confuse with" and PRDSPDUX `§3` + `INT-006`. Never break the `API-001` JSON contract without updating ClientPortal in the same commit.

## PRDSPDUX update rule

`docs/PRDSPDUX.md` is the canonical project source of truth. Whenever any entity, component, rule, flow, UX, schema, permission, integration, or testing behavior changes, update `docs/PRDSPDUX.md` in the same branch/commit as the implementation. Memory notes don't substitute (standing BosOpt rule; see `feedback_features_in_prd.md`).

## Testing expectations

Test methodology: see PRDSPDUX `§11`. Honor the BosOpt-wide "No Production Writes During Testing" rule (use non-prod `--client` or `--no-sheets --excel`).

## No secret handling

Secret storage: see `AUTH-005` and `APP_IDENTITY.md` → "Primary config sources". Keyring only; **no JSON credential files on disk** (global hard rule — see `Projects/CLAUDE.md` STD-019).

## Repo conventions

Repo shape: standalone subprocess (`python src/main.py`), `--json` emits `---JSON_RESULT---` (schema in `API-001`), dual-OS venvs per BosOpt template, no `config/` directory, `_archive/` is historical only.
