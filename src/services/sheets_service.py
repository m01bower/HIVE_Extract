"""Google Sheets service for HIVE_Extract."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from config import SPREADSHEET_ID, GOOGLE_SCOPES, TABS, YEAR_TABS
from settings import get_credentials_path, get_token_path
from logger_setup import get_logger

logger = get_logger()


class SheetsService:
    """Service for interacting with Google Sheets."""

    def __init__(self, spreadsheet_id: str = SPREADSHEET_ID):
        """
        Initialize the Sheets service.

        Args:
            spreadsheet_id: Google Sheets spreadsheet ID
        """
        self.spreadsheet_id = spreadsheet_id
        self._sheets_service: Optional[Resource] = None
        self._gmail_service: Optional[Resource] = None
        self._credentials: Optional[Credentials] = None

    def authenticate(self) -> bool:
        """
        Authenticate with Google APIs using OAuth.

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            creds = None
            token_path = get_token_path()
            credentials_path = get_credentials_path()

            # Load existing token if available
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)

            # If no valid credentials, initiate OAuth flow
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    if not credentials_path.exists():
                        logger.error(f"credentials.json not found at {credentials_path}")
                        return False

                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(credentials_path), GOOGLE_SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # Save the token for future use
                with open(token_path, "w") as token:
                    token.write(creds.to_json())

            self._credentials = creds
            self._sheets_service = build("sheets", "v4", credentials=creds)
            self._gmail_service = build("gmail", "v1", credentials=creds)

            logger.info("Successfully authenticated with Google APIs")
            return True

        except Exception as e:
            logger.error(f"Google authentication failed: {e}")
            return False

    @property
    def sheets(self) -> Resource:
        """Get the Sheets API service."""
        if not self._sheets_service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        return self._sheets_service

    @property
    def gmail(self) -> Resource:
        """Get the Gmail API service."""
        if not self._gmail_service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
        return self._gmail_service

    def verify_tabs_exist(self) -> Tuple[bool, List[str]]:
        """
        Verify all required tabs exist in the spreadsheet.

        Returns:
            Tuple of (all_exist: bool, missing_tabs: List[str])
        """
        try:
            spreadsheet = (
                self.sheets.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute()
            )

            existing_tabs = {
                sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
            }

            required_tabs = set()

            # Add standard tabs
            for tab_config in TABS.values():
                required_tabs.add(tab_config["name"])

            # Add year tabs
            for tab_name in YEAR_TABS.keys():
                required_tabs.add(tab_name)

            missing_tabs = required_tabs - existing_tabs

            if missing_tabs:
                logger.warning(f"Missing tabs: {', '.join(sorted(missing_tabs))}")
                return False, sorted(missing_tabs)

            logger.info("All required tabs verified")
            return True, []

        except Exception as e:
            logger.error(f"Failed to verify tabs: {e}")
            return False, []

    def clear_tab_data(self, tab_name: str, data_start_row: int) -> bool:
        """
        Clear data from a tab while preserving headers.

        Args:
            tab_name: Name of the tab to clear
            data_start_row: Row number where data starts (1-indexed)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the sheet's current dimensions
            range_name = f"'{tab_name}'!A{data_start_row}:ZZ"

            self.sheets.spreadsheets().values().clear(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
            ).execute()

            logger.info(f"Cleared data from {tab_name} starting at row {data_start_row}")
            return True

        except Exception as e:
            logger.error(f"Failed to clear tab {tab_name}: {e}")
            return False

    def write_data(
        self,
        tab_name: str,
        data: List[Dict[str, Any]],
        data_start_row: int,
        include_headers: bool = False,
        header_row: Optional[int] = None,
    ) -> Tuple[bool, int]:
        """
        Write data to a tab.

        Args:
            tab_name: Name of the tab to write to
            data: List of dictionaries to write
            data_start_row: Row number where data starts (1-indexed)
            include_headers: Whether to write headers
            header_row: Row for headers (required if include_headers=True)

        Returns:
            Tuple of (success: bool, rows_written: int)
        """
        if not data:
            logger.warning(f"No data to write to {tab_name}")
            return True, 0

        try:
            # Get headers from the first data item
            headers = list(data[0].keys())

            # Prepare data rows
            rows = []
            for item in data:
                row = [item.get(h, "") for h in headers]
                rows.append(row)

            # Write headers if requested
            if include_headers and header_row:
                header_range = f"'{tab_name}'!A{header_row}"
                self.sheets.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=header_range,
                    valueInputOption="RAW",
                    body={"values": [headers]},
                ).execute()

            # Write data
            data_range = f"'{tab_name}'!A{data_start_row}"
            self.sheets.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=data_range,
                valueInputOption="RAW",
                body={"values": rows},
            ).execute()

            logger.info(f"Wrote {len(rows)} rows to {tab_name}")
            return True, len(rows)

        except Exception as e:
            logger.error(f"Failed to write data to {tab_name}: {e}")
            return False, 0

    def update_timestamp(self, tab_name: str, cell: str = "B1") -> bool:
        """
        Update a timestamp cell in a tab.

        Args:
            tab_name: Name of the tab
            cell: Cell reference for timestamp (default: B1)

        Returns:
            True if successful, False otherwise
        """
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            range_name = f"'{tab_name}'!{cell}"

            self.sheets.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [[timestamp]]},
            ).execute()

            logger.debug(f"Updated timestamp in {tab_name}!{cell}")
            return True

        except Exception as e:
            logger.error(f"Failed to update timestamp in {tab_name}: {e}")
            return False

    def get_tab_headers(self, tab_name: str, header_row: int) -> List[str]:
        """
        Get the headers from a tab.

        Args:
            tab_name: Name of the tab
            header_row: Row number containing headers (1-indexed)

        Returns:
            List of header strings
        """
        try:
            range_name = f"'{tab_name}'!{header_row}:{header_row}"
            result = (
                self.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=range_name)
                .execute()
            )

            values = result.get("values", [[]])
            return values[0] if values else []

        except Exception as e:
            logger.error(f"Failed to get headers from {tab_name}: {e}")
            return []

    def test_access(self) -> bool:
        """
        Test access to the spreadsheet.

        Returns:
            True if access successful, False otherwise
        """
        try:
            spreadsheet = (
                self.sheets.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute()
            )
            title = spreadsheet.get("properties", {}).get("title", "Unknown")
            logger.info(f"Successfully accessed spreadsheet: {title}")
            return True

        except Exception as e:
            logger.error(f"Failed to access spreadsheet: {e}")
            return False
