"""Google Sheets service for HIVE_Extract."""

import os
import re
import unicodedata
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


def _clean_text(value: str) -> str:
    """Clean text to remove encoding artifacts.

    Fixes:
    - Â appearing before spaces (UTF-8 encoding issues)
    - Normalizes Unicode (NFC form)
    Non-breaking spaces (U+00A0) are preserved to match Hive's output.
    """
    # Remove Â encoding artifacts (but preserve non-breaking spaces)
    text = re.sub(r'Â', '', value)

    # Normalize Unicode (NFC form)
    text = unicodedata.normalize('NFC', text)

    return text.strip()


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
        self._credentials: Optional[Credentials] = None

    def authenticate(self) -> bool:
        """
        Authenticate with Google APIs using OAuth.

        Opens a browser window for the user to sign in and authorize access.
        Requires credentials.json in the config directory.

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
                    logger.info("Refreshing Google credentials...")
                    creds.refresh(Request())
                else:
                    if not credentials_path.exists():
                        logger.error(f"credentials.json not found at {credentials_path}")
                        return False

                    logger.info("Opening browser for Google sign-in...")
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(credentials_path), GOOGLE_SCOPES
                    )
                    creds = flow.run_local_server(port=0)

                # Save the token for future use
                token_path.parent.mkdir(parents=True, exist_ok=True)
                with open(token_path, "w") as token:
                    token.write(creds.to_json())
                logger.info("Saved Google credentials")

            self._credentials = creds
            self._sheets_service = build("sheets", "v4", credentials=creds)

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

    @staticmethod
    def _to_cell_value(val: Any) -> Any:
        """Convert a value to a Sheets-compatible cell value and clean text."""
        if val is None:
            return ""
        if isinstance(val, (int, float, bool)):
            return val
        if isinstance(val, str):
            return _clean_text(val)
        if isinstance(val, list):
            joined = ", ".join(str(v) for v in val if v) if val else ""
            return _clean_text(joined)
        if isinstance(val, dict):
            return _clean_text(str(val))
        return _clean_text(str(val))

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

            # Prepare data rows - convert all values to Sheets-compatible types
            rows = []
            for item in data:
                row = [self._to_cell_value(item.get(h, "")) for h in headers]
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

            # Write data - use USER_ENTERED so Sheets parses dates/numbers
            data_range = f"'{tab_name}'!A{data_start_row}"
            self.sheets.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=data_range,
                valueInputOption="USER_ENTERED",
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

    def read_cell(self, tab_name: str, cell: str) -> str:
        """
        Read a single cell value from a tab.

        Args:
            tab_name: Name of the tab
            cell: Cell reference (e.g. "A3")

        Returns:
            Cell value as a string, or empty string if blank/error
        """
        try:
            range_name = f"'{tab_name}'!{cell}"
            result = (
                self.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=range_name)
                .execute()
            )

            values = result.get("values", [[]])
            if values and values[0]:
                return str(values[0][0])
            return ""

        except Exception as e:
            logger.error(f"Failed to read {tab_name}!{cell}: {e}")
            return ""

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
