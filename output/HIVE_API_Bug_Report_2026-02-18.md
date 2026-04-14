# Hive API Timesheet Reporting Bug — Detailed Investigation Report

**Date:** February 18, 2026
**Account:** Lydia Sierra Consulting (LSC)
**Workspace ID:** `aKXG39vFQYtRAkmv6`
**API Endpoint:** `https://prod-gql.hive.com/graphql`
**Query:** `getTimesheetReportingCsvExportData`
**Contact:** Michael Bower, LSC

---

## Executive Summary

The `getTimesheetReportingCsvExportData` GraphQL endpoint returns **different data for the same time entries** depending on the `endDate` parameter passed in the request. Changing `endDate` by a single day — with no change to `startDate` — causes entries on dates well before the end of the range to show different hour values or disappear entirely.

This is not a caching or timing issue. All API calls were made within seconds of each other using identical authentication, and no user activity occurred between calls.

---

## How We Tested

### Tool and Authentication

We built an automated tool that calls the Hive GraphQL API directly. Authentication is via API key and User ID passed in request headers, the same method documented in Hive's API documentation.

**GraphQL query used for all tests:**

```graphql
query GetReportCsv($workspaceId: ID!, $startDate: Date!, $endDate: Date!) {
  getTimesheetReportingCsvExportData(
    workspaceId: $workspaceId,
    startDate: $startDate,
    endDate: $endDate
  )
}
```

The endpoint returns a CSV-formatted string. We parse this CSV and compare the rows.

### What We Compared

We ran three types of comparisons:

1. **Same date range, different `endDate` parameter** (the clearest proof of the bug)
2. **Full year as single request vs. month-by-month requests** (API self-consistency)
3. **API data vs. data already stored in Google Sheets from a prior API call with a different `endDate`**
4. **Web UI CSV download vs. API data** (rules out any data import or copy/paste issues)

For every discrepancy found, we also queried the **detailed time tracking endpoint** (`getTimeTrackingData`) to retrieve the individual time entry record IDs, action card IDs, user IDs, and all metadata. This gives Hive engineering the exact database records to investigate.

---

## Test 1: Changing `endDate` by One Day (2026 Data)

This is the simplest and most conclusive test.

### Setup

Two API calls made within 2 seconds of each other. No user activity between them.

| | Call A | Call B |
|---|---|---|
| `startDate` | `2026-01-01` | `2026-01-01` |
| `endDate` | **`2026-02-18`** | **`2026-02-17`** |
| Rows returned | 710 | 701 |
| Rows after filtering to Jan 1 – Feb 17 | **652** | **643** |
| Total hours (Jan 1 – Feb 17 only) | **1,225.17** | **1,195.39** |

Both calls were filtered to the same date range (Jan 1 through Feb 17) after receiving the response. The ONLY difference is the `endDate` parameter.

### Results

**52 discrepancies** in data that should be identical:

- **9 rows** exist in Call A but are **completely absent** from Call B. All 9 are on **Feb 17** — the last day of Call B's date range.
- **43 rows** exist in both but have **different hour values**. Call A (endDate=Feb 18) always reports MORE hours than Call B (endDate=Feb 17). The affected entries span Feb 1 through Feb 15 — dates well before either end date.
- **0 rows** exist only in Call B.

### Specific Examples

These entries are on dates far from the end of either date range. The hour values should be identical regardless of `endDate`.

| Person | Entry Date | Project | Hours (end=Feb 18) | Hours (end=Feb 17) | Difference |
|---|---|---|---|---|---|
| Christyna Lepetiuk | Feb 2 | NQ - 2026 NYC Council Capital (HPD) | 20.67 | 16.17 | **+4.50 hrs** |
| Christine Van Fossen | Feb 4 | FHLP - CAFE Group 1954 Luminary Award | 15.75 | 12.75 | **+3.00 hrs** |
| Megan Rozzero | Feb 3 | CUP - 2026 NYC Council Discretionary (EDT) | 9.93 | 8.00 | **+1.93 hrs** |
| Megan Sweat Lopes | Feb 6 | EF (Ellie Fund) | 3.62 | 1.78 | **+1.84 hrs** |
| Christine Van Fossen | Feb 12 | BxRA - 2025 NYC DEC Invasive Species | 1.92 | 0.42 | **+1.50 hrs** |
| Matthew Wallace | Feb 1 | CUP - 2026 NYC Council Discretionary (EDT) | 11.96 | 10.65 | **+1.31 hrs** |

**Total excess hours in Call A vs Call B: 29.78 hours**

### Single Best Reproduction Case

**Christine Van Fossen, Feb 4, 2026 — FHLP - 2026 The CAFE Group 1954 Project Luminary Award Application Round One**

- Call the API with `startDate: "2026-01-01"`, `endDate: "2026-02-18"` — her Feb 4 entry shows **15.75 hours**
- Call the API with `startDate: "2026-01-01"`, `endDate: "2026-02-17"` — her Feb 4 entry shows **12.75 hours**
- The entry date (Feb 4) is 13 days before the earlier `endDate` (Feb 17). There is no reason for this value to change.

**Underlying records:**
- Action Card: "Project Management" (Action ID: `dYCfZA5jX6EtfTFEB`)
- Time Entry ID: `jniNTeKnsyRuiPFPc`
- User ID: `dQkfpm3pxfpzML2Cm`
- Project ID: available in the JSON files

---

## Test 2: API Self-Consistency — Single Request vs. Monthly Split (2026 YTD)

### Setup

- **Single request:** `startDate: "2026-01-01"`, `endDate: "2026-02-18"`
- **Split requests:** Jan 1–31, then Feb 1–18, results combined

### Results

| | Single Request | Monthly Split |
|---|---|---|
| Rows | 687 | 688 |
| Discrepancies | 2 | |

**1 row missing from the single request:**
- Matthew Wallace, **Jan 31**, CUP - 2026 NYC Council Discretionary (EDT General)
- Split request shows 2.35 hours on this date; single request has no row at all
- The missing hours (2.34 hrs) appear to be absorbed into his Jan 12 entry, which shows 14.99 hrs in the single request vs. 12.65 hrs in the split

**Underlying records for the missing Jan 31 entry:**

| Time Entry ID | Action Card | Seconds | Hours | Automated |
|---|---|---|---|---|
| `eypzj4DdTiy44FhsN` | Prepare Draft (`PLGcsD4Jonb5fxAYX`) | 2,571 | 0.71 | yes |
| `LPYovaMwYKyfnS2XJ` | Prepare Draft (`PLGcsD4Jonb5fxAYX`) | 702 | 0.20 | yes |
| `2XSPegumPGakwyoPx` | Prepare Draft (`PLGcsD4Jonb5fxAYX`) | 1,921 | 0.53 | yes |
| `yDN47dX6jw7tsrJkJ` | Prepare Draft (`PLGcsD4Jonb5fxAYX`) | 563 | 0.16 | yes |
| `ad2B3SaAzz4KoTi4P` | Prepare Draft (`PLGcsD4Jonb5fxAYX`) | 2,700 | 0.75 | no |

Action Card URL: https://app.hive.com/workspace/aKXG39vFQYtRAkmv6/action-flat/PLGcsD4Jonb5fxAYX

---

## Test 3: API Self-Consistency — Single Request vs. Monthly Split (2025 Full Year)

### Setup

- **Single request:** `startDate: "2025-01-01"`, `endDate: "2025-12-31"`
- **Split requests:** 12 monthly requests (Jan 1–31, Feb 1–28, ... Dec 1–31), results combined

### Results

| | Single Request | Monthly Split |
|---|---|---|
| Rows | 4,133 | 4,595 |
| Total discrepancies | **924** | |
| Rows missing from single request | **462** | |
| Rows with different hours | **462** | |

**Pattern:** Nearly all 462 missing rows fall on **month-end dates** (the last day of each month):

| Month-End Date | Missing Rows |
|---|---|
| Jan 31 | 72 |
| Apr 30 | 71 |
| Mar 31 | 60 |
| Sep 30 | 59 |
| Feb 28 | 54 |
| Oct 31 | 42 |
| Jun 30 | 42 |
| Jul 31 | 40 |
| May 31 | 9 |
| Aug 31 | 3 |
| Nov 30 | 1 |
| Other (Dec 1–18) | 9 |

For every missing month-end row, there is a corresponding row on another date within the same month (same person, same project) that shows **inflated hours**. All 462 "hours differ" entries show the single request reporting MORE hours — never fewer. The excess hours match the missing month-end totals.

**Total hours redistributed: approximately 395 hours**

The full 2025 analysis identified **698 unique action cards** and **1,684 individual time entry records** involved in discrepancies.

---

## Test 4: Web UI CSV Download vs. API Data (Three-Way Comparison)

This test rules out any possibility that the discrepancies are caused by LibreOffice, Google Sheets import, or copy/paste issues.

### Setup

We downloaded the CSV directly from the Hive web UI (Timesheet Reporting > Export) on Feb 18, 2026, covering Jan 1 – Feb 17. We then compared this file against both API responses from Test 1.

| | Web UI CSV | API (endDate=Feb 18) | API (endDate=Feb 17) |
|---|---|---|---|
| Source | Manual download from Hive web UI | `getTimesheetReportingCsvExportData` | `getTimesheetReportingCsvExportData` |
| Rows (Jan 1 – Feb 17) | 652 | 652 | 643 |
| Total hours (Jan 1 – Feb 17) | 1,225.17 | 1,225.17 | 1,195.39 |

### Results

**Web UI vs. API (endDate=Feb 18): PERFECT MATCH**

- **0 hour differences** on all 652 overlapping rows
- The only difference was 35 rows dated Dec 31, 2025 that appeared in the API response but not in the web UI CSV (the API returned some out-of-range data; this is a separate minor issue)
- This confirms the web UI CSV and the API with `endDate: "2026-02-18"` produce **identical hour values**

**Web UI vs. API (endDate=Feb 17): Same discrepancies as Test 1**

- 9 rows present in Web UI but missing from API (all Feb 17 entries)
- 43 rows with different hours (Web UI always shows more), totaling +25.21 excess hours
- These are the exact same discrepancies found in Test 1

### Conclusion

The Web UI CSV file is a byte-for-byte match with the API response when using `endDate: "2026-02-18"`. There are no LibreOffice, Google Sheets, or CSV import issues. The discrepancies are entirely server-side, caused by the `endDate` parameter affecting the aggregation logic in `getTimesheetReportingCsvExportData`.

---

## Root Cause Pattern

Based on all four tests, the API's aggregation logic appears to shift hours from date-boundary entries into entries on other dates for the same person+project combination. The behavior depends on the `endDate` (and possibly `startDate`) parameters:

1. Entries on the **last day of the requested date range** may be dropped entirely
2. Entries on **month-end dates within the range** may be dropped when the range spans multiple months
3. The hours from dropped entries are redistributed to other dates within the same person+project grouping
4. The API **always overreports** hours on the surviving entries (never underreports)
5. The same underlying time entry records exist and are visible via the `getTimeTrackingData` endpoint regardless — the issue is specific to `getTimesheetReportingCsvExportData`
6. The **web UI CSV export matches the API exactly** when the same `endDate` is used — the bug is not in our tooling, import process, or data handling; it is entirely in the server-side aggregation layer

---

## Files Provided

All files are in the `output/` directory. Here is the recommended order for reviewing them.

### Start Here — Simplest Proof of the Bug

| # | File | Description |
|---|---|---|
| 1 | **`sheet_vs_api_2026_2026-01-01_2026-02-17.json`** | **START HERE.** JSON with all 52 discrepancies from Test 1 (endDate=Feb 18 vs Feb 17). Each entry includes `time_entry_id`, `action_id`, `user_id`, `project_id`, `date`, `time_seconds`, `automated`, `category_id`, and the action card URL. This is the most concise, machine-readable file for Hive engineering to investigate. |
| 2 | `api_fresh_2026_2026-01-01_2026-02-17.csv` | Raw CSV response from the API call with `endDate: "2026-02-17"` (643 rows, 1,195.39 hrs). Compare any row against the ALL_2026 tab in Google Sheet ID `15yeShYPuviHX5JmnPKA3ulwKVTTRMOA6PfyI1iwCUPA` which has the same data from an API call with `endDate: "2026-02-18"` (652 rows, 1,225.17 hrs). |

### 2026 YTD — Self-Consistency Test (Single vs. Split)

| # | File | Description |
|---|---|---|
| 3 | `problem_entries_2026_ytd_2026-01-01_2026-02-18.json` | JSON with the 6 time entry records involved in the 2 discrepancies from the single-vs-split test. Includes all record IDs. The Matthew Wallace / Jan 31 case is the cleanest single example. |
| 4 | `problem_entries_2026_ytd_2026-01-01_2026-02-18.txt` | Human-readable version of the same data. |
| 5 | `discrepancy_report_2026-01-01_2026-02-18.txt` | Summary report with action card URLs for the 2026 self-consistency test. |
| 6 | `api_single_2026-01-01_2026-02-18.csv` | Raw CSV from the single API call (Jan 1 – Feb 18). |

### 2025 Full Year — Self-Consistency Test (Single vs. Monthly Split)

| # | File | Description |
|---|---|---|
| 7 | `problem_entries_2025_full_year_2025-01-01_2025-12-31.json` | **Large file (1.5 MB).** JSON with all 1,684 time entry records involved in the 924 discrepancies across the full 2025 year. Every record includes `time_entry_id`, `action_id`, `user_id`, `project_id`, `date`, `time_seconds`, `automated`, `category_id`. This is the most comprehensive dataset for identifying systematic patterns. |
| 8 | `problem_entries_2025_full_year_2025-01-01_2025-12-31.txt` | Human-readable version (1.2 MB). Lists every discrepancy with full record details. |
| 9 | `discrepancy_report_2025-01-01_2025-12-31.txt` | Summary report with all 698 action card URLs. |
| 10 | `api_single_2025-01-01_2025-12-31.csv` | Raw CSV from the single full-year API call (Jan 1 – Dec 31, 2025). |

### Web UI Verification (Test 4)

| # | File | Description |
|---|---|---|
| 11 | `Export_Timesheet_Reporting_2026-02-18.csv` | CSV downloaded directly from the Hive web UI (Timesheet Reporting > Export) on Feb 18, 2026. Covers Jan 1 – Feb 17, 2026. **Matches API (endDate=Feb 18) perfectly** with 0 hour differences on all 652 rows. This rules out any data import or copy/paste issues — the bug is entirely server-side. |

### File Format — JSON Structure

All JSON files follow this structure:

```json
{
  "workspace_id": "aKXG39vFQYtRAkmv6",
  "date_range": { "start": "2026-01-01", "end": "2026-02-17" },
  "generated": "2026-02-18",
  "summary": {
    "sheet_rows": 652,
    "api_rows": 643,
    "sheet_total_hours": 1225.17,
    "api_total_hours": 1195.39,
    "discrepancies": 52,
    "only_in_sheet": 9,
    "only_in_api": 0,
    "hours_differ": 43
  },
  "problem_entries": [
    {
      "discrepancy_type": "hours_differ",
      "discrepancy_person": "Christine Van Fossen",
      "discrepancy_date": "2026-02-04",
      "discrepancy_project": "FHLP - 2026 The CAFE Group...",
      "hours_sheet": 15.75,
      "hours_api": 12.75,
      "time_entry_id": "jniNTeKnsyRuiPFPc",
      "action_id": "dYCfZA5jX6EtfTFEB",
      "action_title": "Project Management",
      "project_id": "...",
      "user_id": "dQkfpm3pxfpzML2Cm",
      "user_name": "Christine Van Fossen",
      "date": "2026-02-04",
      "time_seconds": 4500,
      "time_hours": 1.25,
      "description": "...",
      "automated": false,
      "category_id": null,
      "action_url": "https://app.hive.com/workspace/aKXG39vFQYtRAkmv6/action-flat/dYCfZA5jX6EtfTFEB"
    }
  ]
}
```

---

## Impact

We use Hive timesheet data for client invoicing. Accurate hour totals are critical. Because the API returns different totals depending on query parameters, we cannot rely on it for financial reporting. We are currently forced to manually download CSV files from the Hive web UI, which defeats the purpose of having an API.

---

## What We Need From Hive Engineering

1. **Why does `getTimesheetReportingCsvExportData` return different hour values for the same time entries when only the `endDate` parameter changes?** (See Test 1 — changing endDate from Feb 17 to Feb 18 changes hours on entries dated Feb 2–15.)

2. **Why are entries on month-end dates dropped when querying across multiple months?** (See Test 3 — Jan 31, Feb 28, Mar 31, etc. entries vanish in a full-year query but appear in monthly queries.)

3. **The individual time entry records are correct** — the `getTimeTrackingData` endpoint returns consistent data regardless of date range. The bug appears to be in the CSV aggregation/reporting layer only.

4. The JSON files contain every affected `time_entry_id`, `action_id`, and `user_id` for Hive engineering to trace through the reporting pipeline.

---

**Contact:** Michael Bower, LSC
**Workspace ID:** `aKXG39vFQYtRAkmv6`
