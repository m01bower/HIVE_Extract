"""Configuration constants for HIVE_Extract."""

# Google Sheets Configuration
SPREADSHEET_ID = "15yeShYPuviHX5JmnPKA3ulwKVTTRMOA6PfyI1iwCUPA"

# Tab configurations with row offsets
TABS = {
    "active_projects": {
        "name": "BillingProject_RAW",
        "header_row": 4,
        "data_row": 5,
        "description": "Active Projects",
    },
    "archived_projects": {
        "name": "BillingProject_RAW_Archive",
        "header_row": 4,
        "data_row": 5,
        "description": "Archived Projects",
    },
    "time_tracking": {
        "name": "MonthEXACT_RAW",
        "header_row": 5,
        "data_row": 6,
        "description": "Time Tracking (date range)",
    },
    "month_raw": {
        "name": "Month_RAW",
        "header_row": 4,
        "data_row": 5,
        "description": "Time Reporting - This Month",
    },
    "year_raw": {
        "name": "Year_RAW",
        "header_row": 4,
        "data_row": 5,
        "description": "Time Reporting - This Year",
    },
}

# Year tabs: ALL_2020 through ALL_2026
YEAR_TABS = {
    f"ALL_{year}": {"header_row": 5, "data_row": 6, "description": f"Time Reporting - {year}"}
    for year in range(2020, 2027)
}

# Hive API Configuration
HIVE_API_BASE_URL = "https://app.hive.com/api/v1"

# Google API Scopes
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

# Config file paths (relative to project root)
CONFIG_DIR = "config"
SETTINGS_FILE = "settings.json"
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
