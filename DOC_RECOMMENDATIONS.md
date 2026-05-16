# DOC_RECOMMENDATIONS.md — HIVE_Extract
# Source: Skill A rev 2026-05-15e | evaluated 2026-05-16
# Level: 0 | Structure: High | Stability: stable
# Upstream intent capture: N/A — no substantial business-concept origin
#
# Statuses: pending-triage | open | deferred (reason) | done (date) | declined | needs-info
# Items below were surfaced by Skill A. None have been reviewed yet.
# When you are ready, triage each item — CC can help.
#
# NOTE: HIVE_Extract is Skill A's named negative-control case AND
# the canonical pilot reference shape for the doc-index pattern
# (per parent CLAUDE.md STD-020). The L0+High classification is
# what other BosOpt apps' retrofits should pattern-match against.

## Structure gaps
(none — canonical reference shape; pilot of the doc-index pattern)

## Enrichment
- [ ] Mermaid diagrams under `docs/diagrams/` — pending-triage
  Why: Zero diagrams today. Two flows are non-obvious from prose
  and would benefit from diagrams:
    · The two-pass archived fetch (DEC-003, RULE-004 — the
      Michael Cole gap-closure fix landed 2026-04-22).
    · The All-tab redesign (DEC-002, OPEN-001 — code now owns
      `All!A4:AZ50000`; modes collapsed to {all, projects}).
  What it does: adds 1-2 `*.mmd` files with stable DIAG- IDs
  cited from PRDSPDUX FLOW-/DEC-. Optional; not required for
  the reference shape.

- [ ] `docs/test_scenarios.md` once OPEN-006 lands — pending-triage
  Why: OPEN-006 plans to split the aggregation
  (`get_enriched_monthly_entries`) into a pure function so the
  `_consistency_check` invariant can be unit-tested offline.
  Once tests exist, indexing them with TEST-NNN IDs in
  `docs/test_scenarios.md` makes the safeguard citable.
  What it does: depends on OPEN-006 landing first. Sequence:
  split, write tests, then write the scenarios doc.

## Friction
- [ ] OPEN-003 cross-app: sibling-app copies of `hive_service.py` — pending-triage
  Why: HIVE_Extract is the canonical owner of Hive API access
  per DEC-001. Per memory, `LSC_PrepTimesheets` and
  `WeeklyClientReview` historically had their own copies of
  `hive_service.py`. If those still exist, they should be
  deleted in favor of calling HIVE_Extract via ClientPortal
  `/api/run` (per feedback memory
  `feedback_chain_tools_via_portal_api.md`).
  What it does: not in this repo's scope — verify on the
  siblings and delete sibling copies if present. Tracked in
  MasterToDo TODO-SEC-05.

## Upstream intent capture
N/A — does not apply — pending-triage
  Why: HIVE_Extract is internal automation (Hive timesheets →
  Google Sheets for LSC). Per `upstream-doc-types.md` rev
  2026-05-15c: HIVE_Extract is SPECIFICALLY the project that
  surfaced the need for the N/A category — the original
  four-state model mis-flagged it as a gap. This is the
  reference example of N/A.
  What it does: nothing — the model does not apply.
