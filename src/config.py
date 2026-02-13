"""Configuration constants for HIVE_Extract."""

from pathlib import Path

# Output directory for extract files (relative to project root)
_PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = _PROJECT_ROOT / "output"

# Extract configurations — each produces one Excel file
EXTRACTS = {
    "active_projects": {
        "filename": "BillingProject_RAW.xlsx",
        "description": "Active Projects",
    },
    "archived_projects": {
        "filename": "BillingProject_RAW_Archive.xlsx",
        "description": "Archived Projects",
    },
    "time_tracking": {
        "filename": "MonthEXACT_RAW.xlsx",
        "description": "Time Tracking (date range)",
    },
    "month_raw": {
        "filename": "Month_RAW.xlsx",
        "description": "Time Reporting - This Month",
    },
    "year_raw": {
        "filename": "Year_RAW.xlsx",
        "description": "Time Reporting - This Year",
    },
}

# Year extracts: ALL_2020 through ALL_2026
YEAR_EXTRACTS = {
    f"ALL_{year}": {
        "filename": f"ALL_{year}.xlsx",
        "description": f"Time Reporting - {year}",
    }
    for year in range(2020, 2027)
}

# Hive API Configuration
HIVE_API_BASE_URL = "https://app.hive.com/api/v1"
HIVE_GRAPHQL_URL = "https://prod-gql.hive.com/graphql"

# Config file paths (relative to project root)
CONFIG_DIR = "config"
SETTINGS_FILE = "settings.json"

# Google Sheets Configuration
SPREADSHEET_ID = "15yeShYPuviHX5JmnPKA3ulwKVTTRMOA6PfyI1iwCUPA"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Tab configurations — maps extract keys to sheet tab names
# Rows 1-3 are reserved for formulas, headers go in row 4, data starts in row 5
TABS = {
    "active_projects": {"name": "BillingProject_RAW", "header_row": 4, "data_start_row": 5},
    "archived_projects": {"name": "BillingProject_RAW_Archive", "header_row": 4, "data_start_row": 5},
    "time_tracking": {"name": "MonthEXACT_RAW", "header_row": 4, "data_start_row": 5},
    "month_raw": {"name": "Month_RAW", "header_row": 4, "data_start_row": 5},
    "year_raw": {"name": "Year_RAW", "header_row": 4, "data_start_row": 5},
}

# Year tab configurations - headers in row 5, data starts row 6
YEAR_TABS = {
    f"ALL_{year}": {"name": f"ALL_{year}", "header_row": 5, "data_start_row": 6}
    for year in range(2020, 2027)
}

# Checks tab — used to validate data after extracts complete
CHECKS_TAB = {"name": "Checks", "cell": "A3"}
