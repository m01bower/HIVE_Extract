"""Main entry point for HIVE_Extract."""

import sys
import argparse
from datetime import date
from typing import Dict, Optional, Tuple

from config import TABS, YEAR_TABS, SPREADSHEET_ID
from settings import (
    AppSettings,
    load_settings,
    save_settings,
    ensure_config_dir,
    get_credentials_path,
)
from logger_setup import setup_logger, get_logger
from notification import send_notification, send_error_notification
from services.hive_service import HiveService, HiveCredentials
from services.sheets_service import SheetsService
from gui.date_picker import select_date_range


def run_setup() -> bool:
    """
    Run the setup wizard to configure the application.

    Returns:
        True if setup completed successfully, False otherwise
    """
    logger = get_logger()
    print("\n" + "=" * 60)
    print("HIVE Extract - Setup Wizard")
    print("=" * 60 + "\n")

    # Ensure config directory exists
    config_dir = ensure_config_dir()
    print(f"Config directory: {config_dir}\n")

    # Step 1: Hive API Credentials
    print("-" * 40)
    print("Step 1: Hive API Credentials")
    print("-" * 40)
    print("\nTo get your Hive API credentials:")
    print("  1. Log into Hive at https://app.hive.com")
    print("  2. Click your profile icon (bottom left)")
    print("  3. Go to 'Apps & Integrations' -> 'API'")
    print("  4. Generate a new API key (copy it immediately - shown only once)")
    print("  5. Note your User ID from the same page\n")

    api_key = input("Enter your Hive API key: ").strip()
    if not api_key:
        print("Error: API key is required")
        return False

    user_id = input("Enter your Hive User ID: ").strip()
    if not user_id:
        print("Error: User ID is required")
        return False

    # Test Hive connection
    print("\nTesting Hive API connection...")
    hive = HiveService(HiveCredentials(api_key=api_key, user_id=user_id))
    if not hive.test_connection():
        print("Error: Failed to connect to Hive API. Please check your credentials.")
        return False
    print("Successfully connected to Hive!")

    # Step 2: Google OAuth
    print("\n" + "-" * 40)
    print("Step 2: Google OAuth Setup")
    print("-" * 40)

    credentials_path = get_credentials_path()
    if not credentials_path.exists():
        print(f"\nPlease place your Google OAuth credentials.json file at:")
        print(f"  {credentials_path}")
        print("\nTo get credentials.json:")
        print("  1. Go to Google Cloud Console (https://console.cloud.google.com)")
        print("  2. Create or select a project")
        print("  3. Enable the Google Sheets API and Gmail API")
        print("  4. Go to 'APIs & Services' -> 'Credentials'")
        print("  5. Create OAuth 2.0 Client ID (Desktop application)")
        print("  6. Download the JSON and save as credentials.json")
        input("\nPress Enter when credentials.json is in place...")

        if not credentials_path.exists():
            print("Error: credentials.json not found")
            return False

    print("\nAuthenticating with Google (a browser window will open)...")
    sheets = SheetsService(SPREADSHEET_ID)
    if not sheets.authenticate():
        print("Error: Failed to authenticate with Google")
        return False
    print("Successfully authenticated with Google!")

    # Test spreadsheet access
    print("\nTesting spreadsheet access...")
    if not sheets.test_access():
        print("Error: Cannot access the spreadsheet. Check permissions.")
        return False
    print("Successfully accessed spreadsheet!")

    # Verify tabs
    print("\nVerifying required tabs...")
    all_exist, missing = sheets.verify_tabs_exist()
    if not all_exist:
        print(f"\nWarning: Missing tabs: {', '.join(missing)}")
        print("Please create these tabs in the spreadsheet before running extracts.")
    else:
        print("All required tabs exist!")

    # Step 3: Notification Email
    print("\n" + "-" * 40)
    print("Step 3: Notification Settings")
    print("-" * 40)

    default_email = "finance@lydiasierraconsulting.com"
    email = input(f"\nNotification email [{default_email}]: ").strip()
    if not email:
        email = default_email

    # Save settings
    settings = AppSettings(
        hive_api_key=api_key,
        hive_user_id=user_id,
        notification_email=email,
    )
    save_settings(settings)

    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print(f"\nSettings saved to: {config_dir / 'settings.json'}")
    print("\nYou can now run the extract with: python src/main.py")

    return True


def process_extract(
    hive: HiveService,
    sheets: SheetsService,
    extract_key: str,
    tab_config: dict,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> Dict:
    """
    Process a single extract.

    Args:
        hive: Hive service instance
        sheets: Sheets service instance
        extract_key: Key identifying the extract type
        tab_config: Tab configuration dict
        from_date: Optional start date for time-based extracts
        to_date: Optional end date for time-based extracts

    Returns:
        Result dict with status, rows, and any error
    """
    logger = get_logger()
    tab_name = tab_config["name"]
    data_row = tab_config["data_row"]
    description = tab_config.get("description", tab_name)

    logger.info(f"Processing: {description} -> {tab_name}")

    try:
        # Fetch data based on extract type
        if extract_key == "active_projects":
            data = hive.get_projects(archived=False)
        elif extract_key == "archived_projects":
            data = hive.get_projects(archived=True)
        elif extract_key == "time_tracking":
            if not from_date or not to_date:
                raise ValueError("Date range required for time tracking")
            data = hive.get_time_entries(from_date, to_date)
        elif extract_key == "month_raw":
            # This month's time report
            today = date.today()
            month_start = date(today.year, today.month, 1)
            data = hive.get_time_report(month_start, today)
        elif extract_key == "year_raw":
            # This year's time report
            today = date.today()
            year_start = date(today.year, 1, 1)
            data = hive.get_time_report(year_start, today)
        elif extract_key.startswith("ALL_"):
            # Year-specific extract
            year = int(extract_key.split("_")[1])
            data = hive.get_year_time_entries(year)
        else:
            raise ValueError(f"Unknown extract type: {extract_key}")

        # Clear existing data
        sheets.clear_tab_data(tab_name, data_row)

        # Write new data
        success, rows = sheets.write_data(tab_name, data, data_row)

        if not success:
            return {"status": "error", "rows": 0, "error": "Failed to write data"}

        # Update timestamp
        sheets.update_timestamp(tab_name)

        return {"status": "success", "rows": rows}

    except Exception as e:
        logger.error(f"Error processing {tab_name}: {e}")
        return {"status": "error", "rows": 0, "error": str(e)}


def run_extracts(from_date: date, to_date: date) -> int:
    """
    Run all extracts.

    Args:
        from_date: Start date for time-based extracts
        to_date: End date for time-based extracts

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    logger = get_logger()
    logger.info(f"Starting HIVE Extract: {from_date} to {to_date}")

    # Load settings
    settings = load_settings()
    if not settings.is_configured():
        logger.error("Application not configured. Run with --setup first.")
        return 1

    # Initialize services
    hive = HiveService(
        HiveCredentials(
            api_key=settings.hive_api_key,
            user_id=settings.hive_user_id,
        )
    )

    sheets = SheetsService(SPREADSHEET_ID)

    # Authenticate with Hive
    logger.info("Connecting to Hive...")
    if not hive.test_connection():
        logger.error("Failed to connect to Hive API")
        return 1

    # Authenticate with Google
    logger.info("Authenticating with Google...")
    if not sheets.authenticate():
        logger.error("Failed to authenticate with Google")
        return 1

    # Verify tabs exist
    logger.info("Verifying spreadsheet tabs...")
    all_exist, missing = sheets.verify_tabs_exist()
    if not all_exist:
        logger.warning(f"Missing tabs (will skip): {', '.join(missing)}")

    # Track results
    results: Dict[str, dict] = {}

    # Process standard tabs
    for key, config in TABS.items():
        if config["name"] in missing:
            results[config["name"]] = {
                "status": "skipped",
                "rows": 0,
                "error": "Tab does not exist",
            }
            continue

        result = process_extract(
            hive, sheets, key, config, from_date, to_date
        )
        results[config["name"]] = result

    # Process year tabs
    current_year = date.today().year
    for tab_name, config in YEAR_TABS.items():
        if tab_name in missing:
            results[tab_name] = {
                "status": "skipped",
                "rows": 0,
                "error": "Tab does not exist",
            }
            continue

        # Only process years up to current year
        year = int(tab_name.split("_")[1])
        if year > current_year:
            results[tab_name] = {
                "status": "skipped",
                "rows": 0,
                "error": "Future year",
            }
            continue

        full_config = {"name": tab_name, **config}
        result = process_extract(hive, sheets, tab_name, full_config)
        results[tab_name] = result

    # Log summary
    success_count = sum(1 for r in results.values() if r["status"] == "success")
    error_count = sum(1 for r in results.values() if r["status"] == "error")
    skipped_count = sum(1 for r in results.values() if r["status"] == "skipped")

    logger.info(
        f"Extract complete: {success_count} succeeded, {error_count} failed, {skipped_count} skipped"
    )

    # Send notification
    try:
        send_notification(
            sheets.gmail,
            settings.notification_email,
            results,
            (from_date, to_date),
        )
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

    return 0 if error_count == 0 else 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="HIVE Extract - Export Hive data to Google Sheets"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the setup wizard",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        help="Start date (YYYY-MM-DD) - bypasses date picker",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        help="End date (YYYY-MM-DD) - bypasses date picker",
    )

    args = parser.parse_args()

    # Set up logging
    logger = setup_logger()

    # Run setup if requested
    if args.setup:
        success = run_setup()
        sys.exit(0 if success else 1)

    # Check if settings exist
    settings = load_settings()
    if not settings.is_configured():
        print("Application not configured. Run with --setup first:")
        print("  python src/main.py --setup")
        sys.exit(1)

    # Get date range
    if args.from_date and args.to_date:
        # Use command-line dates
        try:
            from_date = date.fromisoformat(args.from_date)
            to_date = date.fromisoformat(args.to_date)
        except ValueError as e:
            print(f"Invalid date format: {e}")
            print("Use YYYY-MM-DD format")
            sys.exit(1)
    else:
        # Show date picker dialog
        result = select_date_range()
        if result is None:
            print("Operation cancelled")
            sys.exit(0)
        from_date, to_date = result

    # Run extracts
    exit_code = run_extracts(from_date, to_date)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
