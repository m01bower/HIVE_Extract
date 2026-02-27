"""Hive API client using REST (projects) and GraphQL (timesheets)."""

import csv
import io
import re
import requests
from datetime import date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import time
import unicodedata

from logger_setup import get_logger
from config import HIVE_API_BASE_URL, HIVE_GRAPHQL_URL

logger = get_logger()


def clean_text(value: Any) -> Any:
    """Clean text values to remove encoding artifacts.

    Fixes:
    - Â appearing before spaces (UTF-8 encoding issues)
    - Normalizes Unicode (NFC form)
    Non-breaking spaces (U+00A0) are preserved to match Hive's output.
    """
    if not isinstance(value, str):
        return value

    # Remove Â encoding artifacts (but preserve non-breaking spaces)
    text = re.sub(r'Â', '', value)

    # Normalize Unicode (NFC form)
    text = unicodedata.normalize('NFC', text)

    # Strip leading/trailing whitespace
    return text.strip()


@dataclass
class HiveCredentials:
    """Hive API credentials."""

    api_key: str
    user_id: str
    workspace_id: str = ""


class HiveService:
    """Service for interacting with Hive's REST and GraphQL APIs."""

    def __init__(self, credentials: HiveCredentials):
        self.credentials = credentials
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "api_key": credentials.api_key,
            }
        )
        # Cached lookups — loaded once per session
        self._user_lookup: Optional[Dict[str, Dict[str, str]]] = None

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _rest_get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        retries: int = 3,
        retry_delay: float = 1.0,
    ) -> Any:
        url = f"{HIVE_API_BASE_URL}{path}"
        if params is None:
            params = {}
        params["user_id"] = self.credentials.user_id
        params["api_key"] = self.credentials.api_key

        last_error = None
        for attempt in range(retries):
            try:
                response = self.session.get(url, params=params, timeout=60)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(
                    f"REST API request failed (attempt {attempt + 1}/{retries}): {e}"
                )
                if attempt < retries - 1:
                    time.sleep(retry_delay * (attempt + 1))

        raise Exception(
            f"REST API request failed after {retries} attempts: {last_error}"
        )

    def _execute_query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        retries: int = 3,
        retry_delay: float = 1.0,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        graphql_headers = {"user_id": self.credentials.user_id}

        last_error = None
        for attempt in range(retries):
            try:
                response = self.session.post(
                    HIVE_GRAPHQL_URL,
                    json=payload,
                    headers=graphql_headers,
                    timeout=120,
                )
                response.raise_for_status()
                result = response.json()
                if "errors" in result:
                    msgs = [e.get("message", str(e)) for e in result["errors"]]
                    raise Exception(f"GraphQL errors: {'; '.join(msgs)}")
                return result.get("data", {})
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(
                    f"GraphQL request failed (attempt {attempt + 1}/{retries}): {e}"
                )
                if attempt < retries - 1:
                    time.sleep(retry_delay * (attempt + 1))

        raise Exception(
            f"GraphQL request failed after {retries} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Connection / workspace helpers
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        try:
            self._rest_get("/testcredentials")
            logger.info(
                f"Hive API connection verified for user: {self.credentials.user_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Hive: {e}")
            return False

    def get_workspaces(self) -> List[Dict[str, Any]]:
        try:
            result = self._rest_get("/workspaces")
            if isinstance(result, list):
                return result
            return result.get("workspaces", result.get("data", []))
        except Exception as e:
            logger.error(f"Failed to fetch workspaces: {e}")
            return []

    def get_workspace_users(self) -> Dict[str, Dict[str, str]]:
        """Fetch workspace users — cached after first call."""
        if self._user_lookup is not None:
            return self._user_lookup

        workspace_id = self.credentials.workspace_id
        if not workspace_id:
            return {}

        try:
            users = self._rest_get(f"/workspaces/{workspace_id}/users")
            if not isinstance(users, list):
                users = users.get("data", users.get("users", []))

            lookup = {}
            for u in users:
                uid = u.get("id", "")
                profile = u.get("profile", {})
                lookup[uid] = {
                    "fullName": u.get("fullName", ""),
                    "email": u.get("email", ""),
                    "firstName": profile.get("firstName", u.get("firstName", "")),
                    "lastName": profile.get("lastName", u.get("lastName", "")),
                }
            logger.info(f"Loaded {len(lookup)} workspace users")
            self._user_lookup = lookup
            return lookup
        except Exception as e:
            logger.warning(f"Could not fetch workspace users: {e}")
            return {}

    def resolve_user(self, user_id: str) -> Dict[str, str]:
        """Look up a single user by ID via /users/{id} endpoint.

        Used as a fallback when get_workspace_users() doesn't include a user
        (e.g. deactivated/terminated users).  Results are merged into the
        cached lookup so each ID is fetched at most once.
        """
        # Check cache first
        if self._user_lookup and user_id in self._user_lookup:
            return self._user_lookup[user_id]

        try:
            u = self._rest_get(f"/users/{user_id}")
            profile = u.get("profile", {})
            info = {
                "fullName": u.get("fullName", ""),
                "email": u.get("email", ""),
                "firstName": profile.get("firstName", u.get("firstName", "")),
                "lastName": profile.get("lastName", u.get("lastName", "")),
            }
            # Cache for future lookups
            if self._user_lookup is not None:
                self._user_lookup[user_id] = info
            logger.info(f"Resolved missing user {user_id}: {info['fullName']}")
            return info
        except Exception as e:
            logger.warning(f"Could not resolve user {user_id}: {e}")
            return {}

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_date(val: Any) -> str:
        """Strip the time portion from an ISO datetime string."""
        if not val:
            return ""
        if isinstance(val, str) and "T" in val:
            return val.split("T")[0]
        return str(val)

    @staticmethod
    def _minutes_to_hhmm(minutes) -> str:
        """Convert minutes (int or float) to HH:mm string."""
        if not minutes:
            return "0:00"
        total = int(round(minutes))
        h = total // 60
        m = total % 60
        return f"{h}:{m:02d}"

    @staticmethod
    def _extract_custom_field(cf: Dict[str, Any]) -> Any:
        """Extract the display value from a Hive custom field dict."""
        cf_type = cf.get("type", "")
        if cf_type == "date":
            return HiveService._fmt_date(cf.get("dateValue", ""))
        elif cf_type == "number":
            return cf.get("numberValue", "")
        elif cf_type == "select":
            sv = cf.get("selectedValues", [])
            return sv[0] if sv else ""
        else:  # text, url, etc.
            return cf.get("value", "")

    # ------------------------------------------------------------------
    # BillingProject_RAW  /  BillingProject_RAW_Archive
    # ------------------------------------------------------------------

    def get_projects(self, archived: bool = False) -> List[Dict[str, Any]]:
        """Fetch projects formatted for BillingProject_RAW export."""
        workspace_id = self.credentials.workspace_id
        if not workspace_id:
            raise ValueError("workspace_id is required to fetch projects")

        logger.info(
            f"Fetching {'archived' if archived else 'active'} projects from Hive"
        )

        params = {"filters[archived]": "true" if archived else "false"}
        result = self._rest_get(
            f"/workspaces/{workspace_id}/projects", params=params
        )

        if isinstance(result, list):
            projects_list = result
        else:
            projects_list = result.get("data", result.get("projects", []))

        user_lookup = self.get_workspace_users()
        flattened = [
            self._flatten_project(p, user_lookup, archived)
            for p in projects_list
        ]
        logger.info(
            f"Retrieved {len(flattened)} {'archived' if archived else 'active'} projects"
        )
        return flattened

    def _flatten_project(
        self,
        project: Dict[str, Any],
        user_lookup: Dict[str, Dict[str, str]],
        archived: bool = False,
    ) -> Dict[str, Any]:
        """Flatten a project to match BillingProject_RAW column format.

        Standard fields first, then all custom fields dynamically so any
        new custom fields Hive adds automatically become new columns.
        """
        # Resolve member names
        member_ids = project.get("members", [])
        owner_ids = project.get("ownerIds", [])
        all_ids = list(dict.fromkeys(owner_ids + member_ids))  # dedup, preserve order
        member_names = [
            user_lookup.get(uid, {}).get("fullName", uid) for uid in all_ids
        ]
        if project.get("sharingType") == "everyone":
            member_names.append("All members")
        if project.get("accessOption") == "public" and "All members" not in member_names:
            member_names.append("Public project")

        row: Dict[str, Any] = {
            "Project name": project.get("name", ""),
            "Members": ", ".join(member_names),
        }

        if archived:
            row["Archived at"] = self._fmt_date(project.get("modifiedAt", ""))

        row["Status"] = project.get("status", "")
        row["Start Date"] = self._fmt_date(project.get("startDate", ""))
        row["End Date"] = self._fmt_date(project.get("endDate", ""))
        row["Project ID"] = project.get("simpleId", "")

        # Custom fields — add dynamically so new ones auto-appear
        for cf in project.get("projectCustomFields", []):
            label = cf.get("label", "")
            if not label or cf.get("hidden", False):
                continue
            row[label] = self._extract_custom_field(cf)

        return row

    # ------------------------------------------------------------------
    # Projects_ALL  —  combined active + archived
    # ------------------------------------------------------------------

    def get_all_projects(self) -> List[Dict[str, Any]]:
        """Fetch all projects (active + archived) combined into one list."""
        active = self.get_projects(archived=False)
        archived = self.get_projects(archived=True)
        return active + archived

    # ------------------------------------------------------------------
    # MonthEXACT_RAW  —  detailed time tracking entries
    # ------------------------------------------------------------------

    def get_time_entries(
        self,
        from_date: date,
        to_date: date,
    ) -> List[Dict[str, Any]]:
        """Fetch time tracking entries formatted for MonthEXACT_RAW.

        Columns: Project, Parent Project, Time Tracked By, Action Title,
        Time Tracked Date, Tracked (Minutes), Tracked (HH:mm),
        Estimated (Minutes), Estimated (HH:mm), Description, Labels
        """
        logger.info(f"Fetching time entries from {from_date} to {to_date}")

        workspace_id = self.credentials.workspace_id
        if not workspace_id:
            raise ValueError("workspace_id is required to fetch time entries")

        user_lookup = self.get_workspace_users()

        query = """
        query GetTimeTrackingData($workspaceId: ID!, $startDate: Date, $endDate: Date) {
          getTimeTrackingData(workspaceId: $workspaceId, startDate: $startDate, endDate: $endDate) {
            actions {
              _id
              title
              project {
                _id
                name
                parentProject
              }
              labels
              timeTracking {
                actualList {
                  id
                  userId
                  time
                  date
                  description
                  automated
                  categoryId
                }
                estimate
              }
            }
            projects {
              _id
              name
              parentProject
            }
          }
        }
        """

        variables = {
            "workspaceId": workspace_id,
            "startDate": from_date.isoformat(),
            "endDate": to_date.isoformat(),
        }

        result = self._execute_query(query, variables)
        ttd = result.get("getTimeTrackingData", {})
        actions = ttd.get("actions", [])

        # Build project-id → name lookup (including parent resolution)
        project_name_lookup: Dict[str, str] = {}
        project_parent_lookup: Dict[str, str] = {}
        for p in ttd.get("projects", []):
            pid = p.get("_id", "")
            project_name_lookup[pid] = p.get("name", "")
            pp = p.get("parentProject")
            if pp:
                project_parent_lookup[pid] = pp

        def resolve_parent(project_id: str) -> str:
            parent_id = project_parent_lookup.get(project_id, "")
            if parent_id:
                return project_name_lookup.get(parent_id, "")
            return ""

        all_entries: List[Dict[str, Any]] = []
        for action in actions:
            tracking = action.get("timeTracking") or {}
            actual_list = tracking.get("actualList") or []
            if not actual_list:
                continue

            project = action.get("project") or {}
            project_id = project.get("_id", "")
            project_name = project.get("name", "")

            # Resolve parent project name
            parent_project_id = project.get("parentProject", "")
            parent_name = project_name_lookup.get(parent_project_id, "") if parent_project_id else ""

            action_title = action.get("title", "")

            # Labels (returned as IDs — include as-is for now)
            labels_list = action.get("labels") or []
            labels_str = ", ".join(str(l) for l in labels_list) if labels_list else ""

            # Overall estimate in seconds
            overall_estimate = tracking.get("estimate", 0) or 0

            for entry in actual_list:
                uid = entry.get("userId", "")
                user_info = user_lookup.get(uid, {})
                # Fallback: resolve missing users individually (e.g. terminated)
                if uid and not user_info:
                    user_info = self.resolve_user(uid)

                time_seconds = entry.get("time", 0) or 0
                tracked_minutes = round(time_seconds / 60, 2)

                est_minutes = round(overall_estimate / 60, 2) if overall_estimate else 0

                raw_date = entry.get("date", "")
                if isinstance(raw_date, str) and "T" in raw_date:
                    raw_date = raw_date.split("T")[0]

                row: Dict[str, Any] = {
                    "Project": project_name,
                    "Parent Project": parent_name,
                    "Time Tracked By": user_info.get("fullName", ""),
                    "Action Title": action_title,
                    "Time Tracked Date": raw_date,
                    "Tracked (Minutes)": tracked_minutes,
                    "Tracked (HH:mm)": self._minutes_to_hhmm(tracked_minutes),
                    "Estimated (Minutes)": est_minutes,
                    "Estimated (HH:mm)": self._minutes_to_hhmm(est_minutes),
                    "Description": entry.get("description", ""),
                    "Labels": labels_str,
                }

                # Include any extra fields from the entry dynamically
                for k, v in entry.items():
                    if k not in ("id", "userId", "time", "date", "description", "automated", "categoryId"):
                        row.setdefault(k, v)

                all_entries.append(row)

        # Filter to requested date range — Hive API may return extras
        from_str = from_date.isoformat()
        to_str = to_date.isoformat()
        filtered = [
            e for e in all_entries
            if e.get("Time Tracked Date") and from_str <= e["Time Tracked Date"] <= to_str
        ]

        logger.info(f"Retrieved {len(all_entries)} time entries, {len(filtered)} in date range")
        return filtered

    # ------------------------------------------------------------------
    # Month_RAW / Year_RAW / ALL_YYYY  —  timesheet reporting CSV
    # ------------------------------------------------------------------

    def _fetch_timesheet_csv_string(
        self,
        from_date: date,
        to_date: date,
    ) -> str:
        """Fetch the raw CSV string from Hive's timesheet reporting API."""
        logger.info(f"Fetching timesheet report CSV from {from_date} to {to_date}")

        workspace_id = self.credentials.workspace_id
        if not workspace_id:
            raise ValueError("workspace_id is required")

        query = """
        query GetReportCsv($workspaceId: ID!, $startDate: Date!, $endDate: Date!) {
          getTimesheetReportingCsvExportData(
            workspaceId: $workspaceId,
            startDate: $startDate,
            endDate: $endDate
          )
        }
        """

        variables = {
            "workspaceId": workspace_id,
            "startDate": from_date.isoformat(),
            "endDate": to_date.isoformat(),
        }

        result = self._execute_query(query, variables)
        csv_string = result.get("getTimesheetReportingCsvExportData", "")

        if not csv_string:
            logger.warning("Timesheet report CSV returned empty")
            return ""

        row_count = max(len(csv_string.strip().split("\n")) - 1, 0)
        logger.info(f"Retrieved {row_count} timesheet report rows")
        return csv_string

    def get_timesheet_report_csv(
        self,
        from_date: date,
        to_date: date,
    ) -> List[Dict[str, Any]]:
        """Fetch timesheet reporting data as parsed dicts."""
        csv_string = self._fetch_timesheet_csv_string(from_date, to_date)
        if not csv_string:
            return []
        reader = csv.DictReader(io.StringIO(csv_string))
        return list(reader)

    def get_timesheet_report_csv_raw(
        self,
        from_date: date,
        to_date: date,
    ) -> str:
        """Fetch timesheet reporting data as a raw CSV string (written directly to file)."""
        return self._fetch_timesheet_csv_string(from_date, to_date)

    def get_year_timesheet_report(self, year: int) -> List[Dict[str, Any]]:
        """Fetch timesheet report for an entire year as parsed dicts."""
        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)

        today = date.today()
        if to_date > today:
            to_date = today

        return self.get_timesheet_report_csv(from_date, to_date)

    def get_year_timesheet_report_raw(self, year: int) -> str:
        """Fetch timesheet report for an entire year as raw CSV string."""
        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)

        today = date.today()
        if to_date > today:
            to_date = today

        return self.get_timesheet_report_csv_raw(from_date, to_date)
