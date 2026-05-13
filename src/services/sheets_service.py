"""Google Sheets service for HIVE_Extract — extends shared integration.

Adds HIVE-specific features:
- _clean_text: removes UTF-8 encoding artifacts (Â characters)
- write_data: accepts List[Dict] and applies text cleaning
- verify_tabs_exist: uses TABS/YEAR_TABS config (no args)
"""

import re
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

# Add _shared_config to path for shared integrations
_SHARED_CONFIG = Path(__file__).parent.parent.parent.parent / "_shared_config"
sys.path.insert(0, str(_SHARED_CONFIG))

from integrations.sheets_service import SheetsService as _SharedSheetsService  # noqa: E402

from config import GOOGLE_SCOPES, TABS, YEAR_TABS  # noqa: E402
from logger_setup import get_logger  # noqa: E402

logger = get_logger()


def _clean_text(value: str) -> str:
    """Clean text to remove encoding artifacts.

    Fixes:
    - Â appearing before spaces (UTF-8 encoding issues)
    - Normalizes Unicode (NFC form)
    Non-breaking spaces (U+00A0) are preserved to match Hive's output.
    """
    text = re.sub(r'Â', '', value)
    text = unicodedata.normalize('NFC', text)
    return text.strip()


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


class SheetsService:
    """HIVE_Extract Sheets service — wraps shared integration with Hive-specific features."""

    def __init__(self, spreadsheet_id: str, credential_ref: str = "BosOpt",
                 impersonate_email: Optional[str] = None,
                 prefer_oauth: bool = False):
        self._shared = _SharedSheetsService(
            credential_ref=credential_ref,
            scopes=GOOGLE_SCOPES,
            spreadsheet_id=spreadsheet_id,
            impersonate_email=impersonate_email,
            prefer_oauth=prefer_oauth,
        )

    def authenticate(self) -> bool:
        return self._shared.authenticate()

    @property
    def sheets(self):
        """Get the raw Sheets API service resource."""
        return self._shared.service

    def verify_tabs_exist(self) -> Tuple[bool, List[str]]:
        """Verify all required tabs (from TABS + YEAR_TABS config) exist."""
        required_tabs = set()
        for tab_config in TABS.values():
            required_tabs.add(tab_config["name"])
        for tab_name in YEAR_TABS.keys():
            required_tabs.add(tab_name)
        return self._shared.verify_tabs_exist(sorted(required_tabs))

    def clear_tab_data(self, tab_name: str, data_start_row: int) -> bool:
        return self._shared.clear_tab_data(tab_name, data_start_row)

    def write_data(
        self,
        tab_name: str,
        data: List[Dict[str, Any]],
        data_start_row: int,
        include_headers: bool = False,
        header_row: Optional[int] = None,
    ) -> Tuple[bool, int]:
        """Write data to a tab. Accepts List[Dict] and cleans text values."""
        if not data:
            logger.warning(f"No data to write to {tab_name}")
            return True, 0

        headers = list(data[0].keys())
        rows = []
        for item in data:
            row = [_to_cell_value(item.get(h, "")) for h in headers]
            rows.append(row)

        # Write headers if requested
        if include_headers and header_row:
            self._shared.write_range(
                f"'{tab_name}'!A{header_row}",
                [headers],
                value_input_option="RAW",
            )

        return self._shared.write_data(
            tab_name, rows, data_start_row,
        )

    def update_timestamp(self, tab_name: str, cell: str = "B1") -> bool:
        return self._shared.update_timestamp(tab_name, cell)

    def get_tab_headers(self, tab_name: str, header_row: int) -> List[str]:
        return self._shared.get_tab_headers(tab_name, header_row)

    def read_cell(self, tab_name: str, cell: str) -> str:
        return self._shared.read_cell(tab_name, cell)

    def test_access(self) -> bool:
        success, _ = self._shared.test_access()
        return success
