Hive Automation Project Specification for Claude
Goal
Fully automate my 3x/week manual Hive downloads directly into Google Sheets - no Excel files, no copy/paste.

Exact Manual Process to Replicate (4 types Downloads)  and store that data into a specific Goole Sheet Tabs (based upon the download).

Like my other projects, all config data is stored external to the program in a json.

Destination Google sheet is called:  HIVE Data Sets Google Drive ID: 15yeShYPuviHX5JmnPKA3ulwKVTTRMOA6PfyI1iwCUPA

1. Project Navigator 
   Hive UI: Project Navigator → Filter "Active" → Export all columns
              Goes into Tab: BillingProject_RAW
              Column Names start in Row A4, Data in A5


2. Project Navigator: 
    Hive UI: Project Navigator → Filter "Archived" → Export all columns
              Goes into Tab: BillingProject_RAW_Archive
              Column Names start in Row A4, Data in A5

3. Time Tracking: All Projects 
     Hive UI: Time Tracking → → All projects, All Columns, Date range = Last full month - Today()  (I want to be able to select this when I run it) 
              Goes into tab "MonthEXACT_RAW"
              Column Names are in row: 5, Data starts in row 5

4. Time Reporting: All Projects (ONLY filter: ✓ Show archived projects, ✓ Show projects without time (zeros) )
     Hive UI: Time Reporting →   All columns
      Extracts:  Note: HIVE has dynamic fields, so not all the same fields are in every year.  Mostly yes, but not always.
         1) This month  (all columns)   Goes in TAB:  Month_RAW
         2) This year  (same columns)   Goes in TAB:  Year_RAW
         3) ALL years  (same columns)   Goes in TAB:  ALL_YYYY  (From this year down to  ALL_2020.

Again loggin is needed, when done a email message goes out that it is done and what was done.  This time, send the email to finance@lydiasierraconsulting.com  (get email from settings file).

Again this should only be data paste, do not change the formatting. This can be a lot of data, so eventually is it better to do a call to tell it to download the data to excel itself?

Suggestions from Perplexity - Not required, but its trying to help
Technical Requirements
Hive API v3 Endpoints
text
1. Active Projects:  GET /v1/projects?status=active
2. Archived:         GET /v1/projects?status=archived  
3. Time Last Month:  GET /v1/timesheet_entries?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
4. Time This Month:  GET /v1/timesheet_entries?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD
Auth: Authorization: Bearer {API_KEY}

Dynamic Date Logic
python
today = datetime.now()
# Last month (full month)
last_month_end = today.replace(day=1) - timedelta(days=1)  
last_month_start = last_month_end.replace(day=1)
# This month (YTD)
this_month_start = today.replace(day=1)
this_month_end = today
Google Sheets Structure
Pre-create 4 tabs in one master sheet:

text
- "Active Projects"
- "Archived Projects" 
- "Time Last Month"
- "Time This Month"
Execution
Folder: d:\ClientInfo\

Windows Task Scheduler: 3x/week

Service Account JSON: credentials.json

Complete Code Requirements
1. Single hive_sync.py script that:
text
✅ Authenticates to Hive API (API key)
✅ Authenticates to Google Sheets (service account)
✅ Calculates last month/this month dates automatically
✅ Fetches all 4 datasets via API
✅ Clears existing tabs
✅ Writes fresh data to correct tabs (header + rows)
✅ Logs run time + row counts
2. Required libraries
bash
pip install requests gspread google-auth pandas google-auth-oauthlib google-auth-httplib2
3. Config variables at top
python
HIVE_API_KEY = "paste_your_key_here"
SHEET_ID = "paste_your_google_sheet_id_here"
SERVICE_ACCOUNT_FILE = "credentials.json"
4. Exact tab update pattern
python
worksheet.clear()  # Wipe old data
worksheet.update([df.columns.values.tolist()] + df.values.tolist())  # Fresh data
5. Error handling
text
- API failures → log + continue
- Sheet write failures → log + email? 
- Missing tabs → create them
6. Logging
text
hive_sync_2026-01-24.log → "Fetched 47 active projects, 12 archived, 892 time entries"
Deliverables for Claude
hive_sync.py - Complete automation script

run_hive.bat - For Task Scheduler

setup_instructions.md - Service account + tab creation

config_template.py - Keys + IDs to fill

Success Criteria
text
Manual: 15min downloads → copy/paste → Sheets (3x/week)
Auto:   30sec script → Direct to Sheets (3x/week) ✅
Copy/paste this spec directly to Claude. It contains every detail from our conversation. Claude will deliver production-ready code that matches your exact workflow