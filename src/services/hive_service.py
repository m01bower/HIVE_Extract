"""Hive API client using GraphQL."""

import requests
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import time

from logger_setup import get_logger

logger = get_logger()

HIVE_API_URL = "https://app.hive.com/api/v1/graphql"


@dataclass
class HiveCredentials:
    """Hive API credentials."""

    api_key: str
    user_id: str


class HiveService:
    """Service for interacting with Hive's GraphQL API."""

    def __init__(self, credentials: HiveCredentials):
        """
        Initialize the Hive service.

        Args:
            credentials: Hive API credentials
        """
        self.credentials = credentials
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {credentials.api_key}",
            }
        )
        self._workspace_id: Optional[str] = None

    def _execute_query(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        retries: int = 3,
        retry_delay: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Execute a GraphQL query against the Hive API.

        Args:
            query: GraphQL query string
            variables: Optional query variables
            retries: Number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            Query result data

        Raises:
            Exception: If query fails after retries
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        last_error = None
        for attempt in range(retries):
            try:
                response = self.session.post(HIVE_API_URL, json=payload, timeout=60)
                response.raise_for_status()

                result = response.json()

                if "errors" in result:
                    error_messages = [e.get("message", str(e)) for e in result["errors"]]
                    raise Exception(f"GraphQL errors: {'; '.join(error_messages)}")

                return result.get("data", {})

            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"Hive API request failed (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    time.sleep(retry_delay * (attempt + 1))

        raise Exception(f"Hive API request failed after {retries} attempts: {last_error}")

    def test_connection(self) -> bool:
        """
        Test the Hive API connection.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            query = """
            query {
                workspaces {
                    id
                    name
                }
            }
            """
            result = self._execute_query(query)
            workspaces = result.get("workspaces", [])

            if workspaces:
                self._workspace_id = workspaces[0].get("id")
                logger.info(f"Connected to Hive workspace: {workspaces[0].get('name')}")
                return True

            logger.error("No workspaces found")
            return False

        except Exception as e:
            logger.error(f"Failed to connect to Hive: {e}")
            return False

    def get_workspace_id(self) -> Optional[str]:
        """Get the current workspace ID."""
        if not self._workspace_id:
            self.test_connection()
        return self._workspace_id

    def get_projects(self, archived: bool = False) -> List[Dict[str, Any]]:
        """
        Fetch projects from Hive.

        Args:
            archived: If True, fetch archived projects; if False, fetch active projects

        Returns:
            List of project dictionaries
        """
        logger.info(f"Fetching {'archived' if archived else 'active'} projects from Hive")

        all_projects = []
        cursor = None
        page_size = 100

        query = """
        query GetProjects($first: Int, $after: String, $archived: Boolean) {
            projects(first: $first, after: $after, archived: $archived) {
                edges {
                    node {
                        id
                        name
                        description
                        status
                        createdAt
                        updatedAt
                        archived
                        color
                        budget
                        budgetSpent
                        client {
                            id
                            name
                        }
                        owner {
                            id
                            name
                            email
                        }
                    }
                    cursor
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """

        while True:
            variables = {
                "first": page_size,
                "archived": archived,
            }
            if cursor:
                variables["after"] = cursor

            result = self._execute_query(query, variables)
            projects_data = result.get("projects", {})
            edges = projects_data.get("edges", [])

            for edge in edges:
                node = edge.get("node", {})
                all_projects.append(self._flatten_project(node))

            page_info = projects_data.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break

            cursor = page_info.get("endCursor")

        logger.info(f"Retrieved {len(all_projects)} {'archived' if archived else 'active'} projects")
        return all_projects

    def _flatten_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested project data for spreadsheet export."""
        client = project.get("client") or {}
        owner = project.get("owner") or {}

        return {
            "Project ID": project.get("id", ""),
            "Project Name": project.get("name", ""),
            "Description": project.get("description", ""),
            "Status": project.get("status", ""),
            "Created At": project.get("createdAt", ""),
            "Updated At": project.get("updatedAt", ""),
            "Archived": project.get("archived", False),
            "Color": project.get("color", ""),
            "Budget": project.get("budget", ""),
            "Budget Spent": project.get("budgetSpent", ""),
            "Client ID": client.get("id", ""),
            "Client Name": client.get("name", ""),
            "Owner ID": owner.get("id", ""),
            "Owner Name": owner.get("name", ""),
            "Owner Email": owner.get("email", ""),
        }

    def get_time_entries(
        self,
        from_date: date,
        to_date: date,
    ) -> List[Dict[str, Any]]:
        """
        Fetch time tracking entries for a date range.

        Args:
            from_date: Start date
            to_date: End date

        Returns:
            List of time entry dictionaries
        """
        logger.info(f"Fetching time entries from {from_date} to {to_date}")

        all_entries = []
        cursor = None
        page_size = 100

        query = """
        query GetTimeEntries($first: Int, $after: String, $from: Date, $to: Date) {
            timesheetEntries(first: $first, after: $after, from: $from, to: $to) {
                edges {
                    node {
                        id
                        date
                        hours
                        minutes
                        description
                        billable
                        approved
                        createdAt
                        updatedAt
                        user {
                            id
                            name
                            email
                        }
                        project {
                            id
                            name
                        }
                        action {
                            id
                            title
                        }
                    }
                    cursor
                }
                pageInfo {
                    hasNextPage
                    endCursor
                }
            }
        }
        """

        while True:
            variables = {
                "first": page_size,
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            }
            if cursor:
                variables["after"] = cursor

            result = self._execute_query(query, variables)
            entries_data = result.get("timesheetEntries", {})
            edges = entries_data.get("edges", [])

            for edge in edges:
                node = edge.get("node", {})
                all_entries.append(self._flatten_time_entry(node))

            page_info = entries_data.get("pageInfo", {})
            if not page_info.get("hasNextPage", False):
                break

            cursor = page_info.get("endCursor")

        logger.info(f"Retrieved {len(all_entries)} time entries")
        return all_entries

    def _flatten_time_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested time entry data for spreadsheet export."""
        user = entry.get("user") or {}
        project = entry.get("project") or {}
        action = entry.get("action") or {}

        hours = entry.get("hours", 0) or 0
        minutes = entry.get("minutes", 0) or 0
        total_hours = hours + (minutes / 60)

        return {
            "Entry ID": entry.get("id", ""),
            "Date": entry.get("date", ""),
            "Hours": hours,
            "Minutes": minutes,
            "Total Hours": round(total_hours, 2),
            "Description": entry.get("description", ""),
            "Billable": entry.get("billable", False),
            "Approved": entry.get("approved", False),
            "Created At": entry.get("createdAt", ""),
            "Updated At": entry.get("updatedAt", ""),
            "User ID": user.get("id", ""),
            "User Name": user.get("name", ""),
            "User Email": user.get("email", ""),
            "Project ID": project.get("id", ""),
            "Project Name": project.get("name", ""),
            "Action ID": action.get("id", ""),
            "Action Title": action.get("title", ""),
        }

    def get_time_report(
        self,
        from_date: date,
        to_date: date,
        include_archived_projects: bool = True,
        include_projects_without_time: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch time reporting data (aggregated by project/user).

        Args:
            from_date: Start date
            to_date: End date
            include_archived_projects: Include archived projects
            include_projects_without_time: Include projects with no time logged

        Returns:
            List of time report dictionaries
        """
        logger.info(f"Fetching time report from {from_date} to {to_date}")

        # Time reports may use a different query structure
        # For now, we aggregate time entries
        entries = self.get_time_entries(from_date, to_date)

        # Aggregate by user and project
        aggregated: Dict[str, Dict[str, Any]] = {}

        for entry in entries:
            key = f"{entry['User ID']}_{entry['Project ID']}"

            if key not in aggregated:
                aggregated[key] = {
                    "User ID": entry["User ID"],
                    "User Name": entry["User Name"],
                    "User Email": entry["User Email"],
                    "Project ID": entry["Project ID"],
                    "Project Name": entry["Project Name"],
                    "Total Hours": 0,
                    "Billable Hours": 0,
                    "Non-Billable Hours": 0,
                    "Entry Count": 0,
                }

            aggregated[key]["Total Hours"] += entry["Total Hours"]
            aggregated[key]["Entry Count"] += 1

            if entry["Billable"]:
                aggregated[key]["Billable Hours"] += entry["Total Hours"]
            else:
                aggregated[key]["Non-Billable Hours"] += entry["Total Hours"]

        # Round the hours
        for item in aggregated.values():
            item["Total Hours"] = round(item["Total Hours"], 2)
            item["Billable Hours"] = round(item["Billable Hours"], 2)
            item["Non-Billable Hours"] = round(item["Non-Billable Hours"], 2)

        result = list(aggregated.values())
        logger.info(f"Generated time report with {len(result)} entries")
        return result

    def get_year_time_entries(self, year: int) -> List[Dict[str, Any]]:
        """
        Fetch all time entries for a specific year.

        Args:
            year: The year to fetch

        Returns:
            List of time entry dictionaries
        """
        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)

        # Cap to_date at today if year is current year
        today = date.today()
        if to_date > today:
            to_date = today

        return self.get_time_entries(from_date, to_date)
