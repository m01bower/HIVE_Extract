# HIVE_Extract — Project Brief

## Purpose

HIVE_Extract automates the export of project management and time tracking data from Hive (hive.com) into a Google Sheets workbook for Lydia Sierra Consulting (LSC). It replaces a manual process that required 3x/week CSV downloads from the Hive UI, copy/paste into spreadsheets, and column reformatting.

## What It Does

Connects to two Hive APIs (REST and GraphQL), pulls four data sets, and writes them into designated tabs in a shared Google Sheet. After writing, it reads a validation cell from a "Checks" tab and sends a summary notification to a Google Chat space.

### Data Extracts

| Extract | Source | Destination Tab | Description |
|---------|--------|----------------|-------------|
| Active Projects | REST `/workspaces/{id}/projects` | BillingProject_RAW | All active projects with custom fields |
| Archived Projects | REST `/workspaces/{id}/projects` | BillingProject_RAW_Archive | All archived projects with custom fields |
| All Projects | Combined active + archived | Projects_ALL | Union of both sets |
| Time Tracking | GraphQL `getTimeTrackingData` | MonthEXACT_RAW | Per-person, per-project time entries for a date range (default: last 45 days) |

### Blocked Extracts (Hive API Bug)

| Extract | Destination Tab | Status |
|---------|----------------|--------|
| Month_RAW | Month_RAW | Disabled — `getTimesheetReportingCsvExportData` returns incorrect data |
| Year_RAW | Year_RAW | Disabled — same endpoint |
| ALL_2020–ALL_2026 | ALL_{year} | Disabled — same endpoint |

Bug reported to Hive Feb 2026. As of March 2026, still not fixed.

## Execution Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (CLI)                            │
│  Parse args → Load keyring API key → Load MasterConfig          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     run_extracts()                               │
│                                                                 │
│  1. Connect to Hive API (test credentials)                      │
│  2. Authenticate with Google Sheets (BosOpt OAuth)              │
│                                                                 │
│  ┌─── PROJECTS ────────────────────────────────────────────┐    │
│  │  Fetch active projects (REST)                           │    │
│  │  Fetch archived projects (REST)                         │    │
│  │  (fetched once, reused for all 3 tabs)                  │    │
│  │                                                         │    │
│  │  ┌─ PRE-WRITE CHECK ─────────────────────────────────┐  │    │
│  │  │  Read existing row counts (B2) and Amount Awarded  │  │    │
│  │  │  (N1) from both billing tabs. Compare against new  │  │    │
│  │  │  totals. Warn if either drops.                     │  │    │
│  │  └────────────────────────────────────────────────────┘  │    │
│  │                                                         │    │
│  │  Write → BillingProject_RAW                             │    │
│  │  Write → BillingProject_RAW_Archive                     │    │
│  │  Write → Projects_ALL (combined)                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─── TIME TRACKING ──────────────────────────────────────┐     │
│  │  Fetch time entries (GraphQL, date range)               │     │
│  │  Write → MonthEXACT_RAW                                 │     │
│  └─────────────────────────────────────────────────────────┘     │
│                                                                 │
│  3. Read Checks tab (A3) for validation status                  │
│  4. Send Google Chat notification with results                  │
└─────────────────────────────────────────────────────────────────┘
```

### Google Sheets Write Process (per tab)

```
  Read previous totals (pre-write check)
       │
       ▼
  Enforce column order (COLUMN_ORDER in config.py)
       │
       ▼
  Clear rows 4+ (preserves formula rows 1-3)
       │
       ▼
  Write headers (row 4) + data (row 5+)
       │
       ▼
  Update timestamp (cell C1)
```

## Project Structure

```
HIVE_Extract/
├── src/
│   ├── main.py                  # CLI entry point, orchestration
│   ├── config.py                # Constants, tab mappings, column orders, exclusions
│   ├── settings.py              # Path helpers, keyring access, shared config paths
│   ├── logger_setup.py          # Console + daily rotating file logging
│   ├── notification.py          # Google Chat webhook + Gmail notifications
│   ├── gui/
│   │   └── date_picker.py       # Tkinter date range selector (optional)
│   └── services/
│       ├── hive_service.py      # REST + GraphQL Hive API client
│       └── sheets_service.py    # Google Sheets API client
├── tests/                       # Comparison/validation scripts
├── output/                      # Local Excel files (git-ignored)
├── logs/                        # Daily log files (git-ignored)
├── requirements.txt
├── run.bat / run.sh             # OS-specific runners
├── setup_venv.bat / setup_venv.sh
└── hive_api_data_discrepancy_report.md
```

## External Dependencies

### Python Packages (requirements.txt)

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for Hive REST API and webhooks |
| `openpyxl` | Excel file writing (optional local output) |
| `google-auth`, `google-auth-oauthlib` | Google OAuth2 authentication |
| `google-api-python-client` | Google Sheets API |
| `python-dotenv` | Environment config |
| `keyring` | OS keyring access for Hive API key |

### External Services

| Service | What For | Auth Method |
|---------|----------|-------------|
| Hive REST API (`app.hive.com/api/v1`) | Projects, users, workspaces | API key (keyring) + user_id |
| Hive GraphQL (`prod-gql.hive.com/graphql`) | Time tracking data | API key (header) + user_id |
| Google Sheets API | Read/write spreadsheet | OAuth2 (BosOpt credentials) |
| Google Chat Webhook | Post-run notifications | Webhook URL (MasterConfig) |

### Shared Infrastructure

| Resource | Location | Purpose |
|----------|----------|---------|
| MasterConfig | Google Sheet (via `_shared_config/config_reader.py`) | Workspace ID, user ID, sheet IDs, webhook URLs |
| Google OAuth credentials | `_shared_config/clients/BosOpt/credentials.json` | Sheets authentication |
| Google OAuth token | `_shared_config/clients/BosOpt/token.json` | Cached auth token |
| Hive API key | OS keyring (`BosOpt` / `Hive-APIKey`) | Hive API authentication |

## CLI Usage

```bash
# Default: all extracts, last 45 days, write to Google Sheets
python src/main.py

# Projects only
python src/main.py projects

# Time tracking only
python src/main.py monthexact

# Custom date range
python src/main.py --from-date 2026-01-01 --to-date 2026-03-17

# Skip Sheets, write Excel locally
python src/main.py --no-sheets --excel

# Different client (default: LSC)
python src/main.py --client LSC

# Setup wizard (configure API key)
python src/main.py --setup
```

## Data Integrity Features

- **Pre-write check**: Before overwriting billing project tabs, reads existing row counts and Amount Awarded totals. Warns if new data has fewer rows or lower totals.
- **Post-write validation**: Reads cell A3 from the "Checks" tab (contains a formula that validates data consistency). Logs and reports "ALL GOOD" or "PROBLEMS DETECTED".
- **Project exclusion**: Filters 8 template/internal projects that the Hive API returns but the UI hides, ensuring row counts match the Hive UI exactly.
- **Column ordering**: Enforced column order per tab so sheet formulas always reference correct columns.
- **Date filtering**: Time entries are filtered to the requested date range (Hive API sometimes returns extras).

## Dual-OS Support

| OS | Virtual Environment | Run Command |
|----|-------------------|-------------|
| Windows | `venv-win/` | `run.bat` |
| Linux | `venv-linux/` | `./run.sh` |

Code uses `pathlib` throughout for cross-platform paths. Config and credentials shared across both environments via `_shared_config/`.
