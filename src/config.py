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
    "all_projects": {
        "filename": "Projects_ALL.xlsx",
        "description": "All Projects (Active + Archived)",
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

# Settings file name (stored in _shared_config/apps/HIVE_Extract/)
SETTINGS_FILE = "settings.json"

# Google Sheets Configuration
# SPREADSHEET_ID now comes from MasterConfig (client.sheets.hive_extract_sheet_id)
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
    "all_projects": {"name": "Projects_ALL", "header_row": 4, "data_start_row": 5},
}

# Year tab configurations - headers in row 5, data starts row 6
YEAR_TABS = {
    f"ALL_{year}": {"name": f"ALL_{year}", "header_row": 5, "data_start_row": 6}
    for year in range(2020, 2027)
}

# Required column orders — columns must appear in this order.
# Any extra columns from the API are appended at the end.
COLUMN_ORDER = {
    "all_projects": [
        "Members", "Project name", "Client Name", "Project Codes",
        "LSC Prospect?", "Project Type", "Funder Type", "Amount Requested",
        "Amount Awarded", "Grant Period Start Date", "Grant Period End Date",
        "Renew Next Elgible Application Cycle?", "Stage", "Submission Year",
        "Funder Notification Date", "Note(s)", "Funder Name", "Date Submitted",
        "Grant Type",
    ],
    "active_projects": [
        "Project name", "Members", "Status", "Start Date", "End Date",
        "Project ID", "Client Name", "Funder Name", "Submission Year",
        "Date Submitted", "Stage", "Funder Notification Date",
        "Amount Requested", "Amount Awarded", "Project Type", "Grant Type",
        "Funder Type", "Grant Period Start Date", "Grant Period End Date",
        "Renew Next Elgible Application Cycle?", "Project Codes", "Note(s)",
        "LSC Prospect?",
    ],
    "archived_projects": [
        "Project name", "Members", "Archived at", "Status", "Start Date",
        "End Date", "Project ID", "Client Name", "Funder Name",
        "Submission Year", "Date Submitted", "Stage",
        "Funder Notification Date", "Amount Requested", "Amount Awarded",
        "Project Type", "Grant Type", "Funder Type",
        "Grant Period Start Date", "Grant Period End Date",
        "Renew Next Elgible Application Cycle?", "Project Codes", "Note(s)",
        "LSC Prospect?",
    ],
    "time_tracking": [
        "Time Tracked By", "Project", "Parent Project", "Action Title",
        "Time Tracked Date", "Tracked (Minutes)", "Tracked (HH:mm)",
        "Estimated (Minutes)", "Estimated (HH:mm)", "Description", "Labels",
    ],
}

# Columns to always exclude from output (not useful)
EXCLUDED_COLUMNS = {"Monthly Budget"}

# Projects the API returns but the Hive UI hides (templates, internal items).
# These are excluded from project extracts to match the UI export.
EXCLUDED_PROJECTS_ACTIVE = {
    "Irma's Clients - Grant Report Template",
    "Irma's Clients - LOI Template",
    "Irma's Clients - Proposal Template",
    "Lexi's Clients - Grant Report Template",
    "Lexi's Clients - LOI Template",
    "Lexi's Clients - Proposal Template",
}
EXCLUDED_PROJECTS_ARCHIVED = {
    "Monthly Work",
    "Prospect Review Template",
}

# Checks tab — used to validate data after extracts complete
CHECKS_TAB = {"name": "Checks", "cell": "A3"}
