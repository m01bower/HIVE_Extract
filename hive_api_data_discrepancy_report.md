# Hive API Timesheet Data Discrepancy — Support Request

**Date:** February 16, 2026
**Account:** Lydia Sierra Consulting (LSC)
**Workspace ID:** aKXG39vFQYtRAkmv6

---

## What We Do

We are a consulting firm that tracks all staff time in Hive using the time tracking feature. Accurate hour totals are critical to our business — we use this data for client invoicing, utilization reporting, and financial management.

To streamline our workflow, we built an automated tool that pulls our timesheet data from Hive into Google Sheets on a scheduled basis. This eliminates the need to manually download CSV files from the Hive web interface every time we need updated data.

---

## How Our Tool Works

Our tool uses the Hive GraphQL API to export the same timesheet reporting data that is available through the Hive web UI's CSV download feature. Specifically, we call the `getTimesheetReportingCsvExportData` endpoint:

```
Endpoint: https://prod-gql.hive.com/graphql

Query:
  getTimesheetReportingCsvExportData(
    workspaceId: "aKXG39vFQYtRAkmv6",
    startDate: "2025-01-01",
    endDate: "2025-12-31"
  )
```

We authenticate using a standard Hive API key and User ID, passed via request headers. The API returns a CSV-formatted string containing the same columns as the web UI export (Person, Email, Role, Project, Date, Hours, Category, etc.). We parse this CSV and write the data to Google Sheets.

---

## The Problem

The data returned by the GraphQL API does not match the data we get when we manually download the same report from the Hive web UI. We tested this carefully:

1. Downloaded a CSV from the Hive web UI (Timesheet Reporting, same workspace, same date ranges)
2. Within 30 seconds, ran our automated tool to pull the same data via the API
3. Compared the results

**No one was working at the time** — all staff were on vacation — so the underlying data could not have changed between the two exports.

The API consistently returns **fewer rows** and **lower hour values** than the web UI download.

---

## 2025 Full Year Comparison (Jan 1 – Dec 31)

| Export Method | Rows | Total Hours |
|---------------|------|-------------|
| Hive Web UI CSV Download | 4,103 | 9,812.62 |
| GraphQL API | 4,094 | 9,690.69 |
| **Difference** | **9 rows missing** | **121.93 hours missing** |

### 9 Rows Completely Missing From the API

These time entries appear in the web UI download but are entirely absent from the API response:

| Person | Date | Hours | Project | Category |
|--------|------|-------|---------|----------|
| Lydia Sierra | Dec 1, 2025 | 57.00 | LSC Internal Work | Administrative Tasks |
| Lydia Sierra | Dec 18, 2025 | 5.63 | LSC - Business Development | |
| Lexi Brown | Dec 1, 2025 | 9.88 | LSC - Marketing | |
| Lexi Brown | Dec 1, 2025 | 29.45 | LSC Internal Work | Executive Assistance |
| Megan Rozzero | Dec 1, 2025 | 8.40 | LSC Internal Work | Administrative Tasks |
| Megan Rozzero | Dec 2, 2025 | 0.03 | UB - SAM.gov Update Required | |
| Megan Rozzero | Dec 3, 2025 | 1.59 | LSC Internal Work | |
| Irma Frias | Dec 3, 2025 | 0.50 | UB - SAM.gov Update Required | |
| Irma Frias | Dec 9, 2025 | 0.32 | LSC Internal Work | |

Note: Irma Frias is a former employee. Her time entries still appear in the web UI download (as expected — we need historical data for invoicing) but are missing from the API.

### 36 Rows With Wrong Hour Values

Beyond the missing rows, 36 entries exist in both the UI download and the API, but the API reports lower hours for every single one. A sample:

| Person | Date | Project | Web UI Hours | API Hours | Short By |
|--------|------|---------|-------------|-----------|----------|
| Lexi Brown | Dec 1 | LSC - Financial Management | 19.08 | 16.02 | 3.06 |
| Jamie Andersson | Dec 1 | LSC Internal Work | 21.33 | 20.33 | 1.00 |
| Megan Rozzero | Dec 1 | LSC Internal Work [Coordination Meetings] | 13.52 | 12.88 | 0.64 |
| Lexi Brown | Dec 3 | LSC Internal Work [Coordination Meetings] | 8.73 | 8.10 | 0.63 |
| Jamie Andersson | Dec 4 | NQ (Nos Quedamos) | 6.58 | 6.25 | 0.33 |
| Jamie Andersson | Dec 9 | BxRA (Bronx River Alliance) | 1.42 | 1.25 | 0.17 |
| Lexi Brown | Dec 2 | NQ (Nos Quedamos) | 2.65 | 2.48 | 0.17 |

The pattern holds across all 36 rows — the API always underreports, never overreports.

---

## 2026 Year-to-Date Comparison (Jan 1 – Feb 16)

| Export Method | Rows | Total Hours |
|---------------|------|-------------|
| Hive Web UI CSV Download | 631 | 1,133.80 |
| GraphQL API | 631 | 1,126.98 |
| **Difference** | **0 rows** | **6.82 hours missing** |

Same row count, but 17 rows have lower hours in the API. Examples:

| Person | Date | Project | Web UI Hours | API Hours | Short By |
|--------|------|---------|-------------|-----------|----------|
| Jamie Andersson | Feb 3 | AI - Annual Prospect Research | 1.25 | 0.83 | 0.42 |
| Jamie Andersson | Feb 3 | BxRA - Annual Prospect Research | 1.25 | 0.83 | 0.42 |
| Jamie Andersson | Feb 3 | CCHP - Annual Prospect Research | 1.25 | 0.83 | 0.42 |
| *(... same pattern for 6 more projects on the same date)* | | | | | |
| Megan Rozzero | Feb 8 | NQ - 2026 NYC Council Discretionary Funding | 2.07 | 1.20 | 0.87 |
| Megan Sweat Lopes | Feb 9 | LSC - Prospect Research Development | 0.92 | 0.42 | 0.50 |

---

## The API Is Also Inconsistent With Itself

We discovered that requesting the exact same 2026 data using different date range parameters returns different results:

| How We Asked | Rows | Total Hours |
|--------------|------|-------------|
| Single request: Jan 1 to Feb 16 | 631 | 1,126.98 |
| Two requests: Jan 1–31 then Feb 1–16, combined | 631 | 1,124.64 |

Same rows returned both ways, but the hour values differ by 2.34 hours depending on whether we ask for the data in one request or two.

---

## Summary of Issues

1. **Missing rows** — The API omits time entries that appear in the web UI download, including entries for former employees whose historical data we need.

2. **Underreported hours** — Where the same entry exists in both exports, the API consistently returns lower hour values. We have not found a single case where the API reports higher hours.

3. **Internal inconsistency** — The API returns different hour values for the same time entries depending on the date range parameters used in the request. The same query with different start/end dates produces different hour totals.

4. **Not a timing issue** — All comparisons were done within 30 seconds of each other with no user activity in between (staff on vacation). The discrepancies also affect dates going back months, not just recent entries.

---

## Impact

We use Hive timesheet data for client invoicing. The hour totals must be accurate. Currently we cannot rely on the API for this purpose and must continue downloading CSV files manually from the web UI, which defeats the purpose of having an API.

---

## What We Need

We'd like the Hive engineering team to investigate:

1. Why does `getTimesheetReportingCsvExportData` return different data than the web UI CSV download?
2. Why are some time entries missing entirely from the API response?
3. Why does the same endpoint return different hour values depending on the date range parameters?
4. Is there a different API endpoint or approach we should be using to get data that matches the web UI export?

We're happy to provide additional test data, API request logs, or access to our comparison tooling if that would help with the investigation.

---

**Contact:** Michael Bower, LSC
**Workspace ID:** aKXG39vFQYtRAkmv6
**API Endpoint Used:** `https://prod-gql.hive.com/graphql`
**Query:** `getTimesheetReportingCsvExportData`
