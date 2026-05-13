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
from config import HIVE_API_BASE_URL, HIVE_GRAPHQL_URL, EXCLUDED_PROJECTS_ACTIVE, EXCLUDED_PROJECTS_ARCHIVED

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
        last_response_body = ""
        for attempt in range(retries):
            try:
                response = self.session.post(
                    HIVE_GRAPHQL_URL,
                    json=payload,
                    headers=graphql_headers,
                    timeout=120,
                )
                if not response.ok:
                    last_response_body = response.text[:1000]
                    logger.error(
                        f"GraphQL HTTP {response.status_code}: {last_response_body}"
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

        detail = f" | Response: {last_response_body}" if last_response_body else ""
        raise Exception(
            f"GraphQL request failed after {retries} attempts: {last_error}{detail}"
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
            # Cache the failure so we don't retry 3x per entry for deleted users
            if self._user_lookup is not None:
                self._user_lookup[user_id] = {}
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
        """Extract the display value from a Hive custom field dict.

        Returns empty string (never None) so downstream consumers don't have
        to .get(x) or "" defensively — Hive returns None for empty number
        fields, which was rendering as literal "None" in output tabs.
        """
        cf_type = cf.get("type", "")
        if cf_type == "date":
            return HiveService._fmt_date(cf.get("dateValue", ""))
        elif cf_type == "number":
            v = cf.get("numberValue")
            return v if v is not None else ""
        elif cf_type == "select":
            sv = cf.get("selectedValues", [])
            return sv[0] if sv else ""
        else:  # text, url, etc.
            v = cf.get("value")
            return v if v is not None else ""

    # ------------------------------------------------------------------
    # Time categories — resolve categoryId to human-readable name
    # ------------------------------------------------------------------

    def get_time_categories(self) -> Dict[str, str]:
        """Fetch time categories for the workspace. Returns {categoryId: name}."""
        workspace_id = self.credentials.workspace_id
        if not workspace_id:
            return {}

        query = """
        query GetTimeCategories($workspaceId: ID!) {
          getTimeCategories(workspaceId: $workspaceId) {
            _id
            name
          }
        }
        """
        try:
            result = self._execute_query(query, {"workspaceId": workspace_id})
            categories = result.get("getTimeCategories", [])
            lookup = {c["_id"]: c.get("name", "") for c in categories if c.get("_id")}
            logger.info(f"Loaded {len(lookup)} time categories")
            return lookup
        except Exception as e:
            logger.warning(f"Could not fetch time categories: {e}")
            return {}

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
        # Filter out projects the API returns but the Hive UI hides
        excluded_set = EXCLUDED_PROJECTS_ARCHIVED if archived else EXCLUDED_PROJECTS_ACTIVE
        before = len(flattened)
        flattened = [p for p in flattened if p.get("Project name", "") not in excluded_set]
        excluded = before - len(flattened)
        if excluded:
            logger.info(f"Excluded {excluded} hidden projects (templates/internal)")
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

        Uses getActionsByWorkspace with pagination since Hive removed
        the getTimeTrackingData query (April 2026).

        Columns: Project, Parent Project, Time Tracked By, Action Title,
        Time Tracked Date, Tracked (Minutes), Tracked (HH:mm),
        Estimated (Minutes), Estimated (HH:mm), Description, Labels
        """
        logger.info(f"Fetching time entries from {from_date} to {to_date}")

        workspace_id = self.credentials.workspace_id
        if not workspace_id:
            raise ValueError("workspace_id is required to fetch time entries")

        user_lookup = self.get_workspace_users()

        # INTERIM TWO-PASS (2026-04-22):
        # Hive confirmed they're implementing a single-query solution; until it ships,
        # we run two passes — `archived: false` (standard actions) and `archived: true`
        # (individually-archived action cards) — both with `includeArchivedProjects: true`.
        # Results are deduplicated by (action_id, entry_id). This matches the Hive UI
        # timesheet export exactly. When Hive ships the single-query version, replace
        # the two-pass loop with one call.
        query = """
        query GetActions($workspaceId: ID!, $first: Int, $after: ID,
                         $includeArchivedProjects: Boolean, $archived: Boolean) {
          getActionsByWorkspace(
            workspaceId: $workspaceId,
            first: $first,
            after: $after,
            excludeCompletedActions: false,
            includeArchivedProjects: $includeArchivedProjects,
            archived: $archived
          ) {
            edges {
              node {
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
              cursor
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """

        from_str = from_date.isoformat()
        to_str = to_date.isoformat()

        # Build project-name lookup from paginated results (shared across both passes)
        project_name_lookup: Dict[str, str] = {}

        all_entries: List[Dict[str, Any]] = []
        seen_entries: set = set()  # (action_id, entry_id) — dedup across the two passes
        total_actions_both = 0
        page_size = 100

        for archived_flag in (False, True):
            pass_label = "archived-actions" if archived_flag else "standard"
            cursor = None
            page = 0
            total_actions = 0

            while True:
                page += 1
                variables: Dict[str, Any] = {
                    "workspaceId": workspace_id,
                    "first": page_size,
                    "includeArchivedProjects": True,
                    "archived": archived_flag,
                }
                if cursor:
                    variables["after"] = cursor

                result = self._execute_query(query, variables)
                connection = result.get("getActionsByWorkspace", {})
                edges = connection.get("edges", [])
                total_actions += len(edges)

                for edge in edges:
                    action = edge.get("node", {})
                    action_id = action.get("_id", "")
                    tracking = action.get("timeTracking") or {}
                    actual_list = tracking.get("actualList") or []
                    if not actual_list:
                        continue

                    project = action.get("project") or {}
                    project_id = project.get("_id", "")
                    project_name = project.get("name", "")
                    parent_project_id = project.get("parentProject", "")

                    # Cache project names for parent resolution
                    if project_id and project_name:
                        project_name_lookup[project_id] = project_name

                    parent_name = (
                        project_name_lookup.get(parent_project_id, "")
                        if parent_project_id
                        else ""
                    )

                    action_title = action.get("title", "")

                    labels_list = action.get("labels") or []
                    labels_str = (
                        ", ".join(str(l) for l in labels_list) if labels_list else ""
                    )

                    overall_estimate = tracking.get("estimate", 0) or 0

                    for entry in actual_list:
                        entry_id = entry.get("id", "")
                        dedup_key = (action_id, entry_id)
                        if dedup_key in seen_entries:
                            continue

                        raw_date = entry.get("date", "")
                        if isinstance(raw_date, str) and "T" in raw_date:
                            raw_date = raw_date.split("T")[0]

                        # Skip entries outside the date range early
                        if not raw_date or raw_date < from_str or raw_date > to_str:
                            continue

                        seen_entries.add(dedup_key)

                        uid = entry.get("userId", "")
                        user_info = user_lookup.get(uid, {})
                        if uid and not user_info:
                            user_info = self.resolve_user(uid)

                        time_seconds = entry.get("time", 0) or 0
                        tracked_minutes = round(time_seconds / 60, 2)
                        est_minutes = (
                            round(overall_estimate / 60, 2) if overall_estimate else 0
                        )

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

                        # Preserve categoryId for monthly aggregation
                        row["categoryId"] = entry.get("categoryId", "")

                        for k, v in entry.items():
                            if k not in (
                                "id", "userId", "time", "date",
                                "description", "automated", "categoryId",
                            ):
                                row.setdefault(k, v)

                        all_entries.append(row)

                page_info = connection.get("pageInfo", {})
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

            logger.info(
                f"  pass '{pass_label}': {page} pages, {total_actions} actions scanned"
            )
            total_actions_both += total_actions

        logger.info(
            f"Scanned {total_actions_both} actions across 2 passes, "
            f"found {len(all_entries)} unique time entries in date range"
        )
        return all_entries

    # ------------------------------------------------------------------
    # Monthly-aggregated time entries (replaces broken CSV endpoint)
    # ------------------------------------------------------------------

    def get_time_entries_monthly(
        self,
        from_date: date,
        to_date: date,
    ) -> List[Dict[str, Any]]:
        """Fetch time entries and aggregate by Person + Project + Category + Month.

        Uses getActionsByWorkspace (working endpoint) as the data source,
        then groups and sums hours to produce the same shape as the broken
        getTimesheetReportingCsvExportData endpoint — but at monthly
        granularity instead of daily.

        Returns rows sorted by Person, Project, Category, Month.
        """
        logger.info(
            f"Fetching time entries for monthly aggregation: {from_date} to {to_date}"
        )

        # Get category names so we can resolve categoryId → name
        category_lookup = self.get_time_categories()

        # Get all daily time entries (reuse existing method)
        daily_entries = self.get_time_entries(from_date, to_date)
        if not daily_entries:
            return []

        # Build user email/role lookup
        user_lookup = self.get_workspace_users()

        # Build project metadata lookup from project data
        project_meta = self._build_project_metadata_lookup()

        # Aggregate: group by (Person, Email, Project, Category, Month)
        from collections import defaultdict
        agg: Dict[tuple, Dict[str, Any]] = {}

        for entry in daily_entries:
            person = entry.get("Time Tracked By", "")
            project_name = entry.get("Project", "")
            raw_date = entry.get("Time Tracked Date", "")

            # Resolve category name from categoryId
            category_id = entry.get("categoryId", "")
            category_name = category_lookup.get(category_id, "") if category_id else ""

            # Month key: first day of the month
            if raw_date and len(raw_date) >= 7:
                month_key = raw_date[:7] + "-01"  # YYYY-MM-01
            else:
                continue

            # Find user email from the user lookup
            email = ""
            role = ""
            for uid, info in user_lookup.items():
                if info.get("fullName") == person:
                    email = info.get("email", "")
                    break

            # Aggregation key
            key = (person, email, project_name, category_name, month_key)

            if key not in agg:
                # Get project metadata
                meta = project_meta.get(project_name, {})
                agg[key] = {
                    "Person": person,
                    "Email": email,
                    "Project": project_name,
                    "Client Name": meta.get("Client Name", ""),
                    "Category": category_name,
                    "Date unit": "Month",
                    "Date": month_key,
                    "Hours": 0.0,
                }
            agg[key]["Hours"] += entry.get("Tracked (Minutes)", 0) / 60

        # Round hours only after all entries are summed
        for row in agg.values():
            row["Hours"] = round(row["Hours"], 2)

        # Sort by Person, Project, Category, Date
        rows = sorted(agg.values(), key=lambda r: (
            r["Person"], r["Project"], r["Category"], r["Date"]
        ))

        logger.info(
            f"Aggregated {len(daily_entries)} daily entries into "
            f"{len(rows)} monthly rows"
        )
        return rows

    # ------------------------------------------------------------------
    # All / Month tab enriched monthly aggregation
    # ------------------------------------------------------------------

    def get_enriched_monthly_entries(
        self,
        from_date: date,
        to_date: date,
        role_lookup: Optional[Dict[str, str]] = None,
        daily_entries: Optional[List[Dict[str, Any]]] = None,
        active_projects: Optional[List[Dict[str, Any]]] = None,
        archived_projects: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch time entries aggregated by Person + Project + Category + Month,
        enriched with project metadata to match the All tab layout.

        Output keys match the 27 canonical columns in COLUMN_ORDER["all_enriched"].

        When daily_entries / active_projects / archived_projects are pre-fetched
        by the caller, they're used as-is (no extra API calls). This lets the
        caller do one fetch of time entries and reuse it for both MonthEXACT_RAW
        and the All tab — the source of the "single fetch, dual write" guarantee.
        """
        role_lookup = role_lookup or {}

        if daily_entries is None:
            daily_entries = self.get_time_entries(from_date, to_date)
        if not daily_entries:
            return []

        # Category names
        category_lookup = self.get_time_categories()

        # User email lookup — merge workspace-users + any resolved users
        user_lookup = self.get_workspace_users()
        email_by_name: Dict[str, str] = {}
        for v in user_lookup.values():
            name = v.get("fullName", "")
            if name:
                email_by_name[name] = v.get("email", "")

        # Project metadata lookup — active + archived, with custom fields
        project_meta = self._build_project_metadata_lookup(
            active_data=active_projects,
            archived_data=archived_projects,
        )

        agg: Dict[tuple, Dict[str, Any]] = {}

        for entry in daily_entries:
            person = entry.get("Time Tracked By", "")
            project_name = entry.get("Project", "")
            raw_date = entry.get("Time Tracked Date", "")

            category_id = entry.get("categoryId", "")
            category_name = category_lookup.get(category_id, "") if category_id else ""

            if raw_date and len(raw_date) >= 7:
                month_key = raw_date[:7] + "-01"  # YYYY-MM-01
            else:
                continue

            key = (person, project_name, category_name, month_key)

            if key not in agg:
                email = email_by_name.get(person, "")

                # Role lookup — try email first, fall back to name
                role = ""
                if email:
                    role = role_lookup.get(email.lower(), "")
                if not role and person:
                    role = role_lookup.get(person.lower(), "")

                meta = project_meta.get(project_name, {})

                agg[key] = {
                    "Person": person,
                    "Email": email,
                    "Role": role,
                    "Project": project_name,
                    "Client Name": meta.get("Client Name", ""),
                    "Project Codes": meta.get("Project Codes", ""),
                    "LSC Prospect?": meta.get("LSC Prospect?", ""),
                    "Project Type": meta.get("Project Type", ""),
                    "Funder Type": meta.get("Funder Type", ""),
                    "Amount Requested": meta.get("Amount Requested", ""),
                    "Amount Awarded": meta.get("Amount Awarded", ""),
                    "Grant Period Start Date": meta.get("Grant Period Start Date", ""),
                    "Grant Period End Date": meta.get("Grant Period End Date", ""),
                    "Renew Next Elgible Application Cycle?": meta.get(
                        "Renew Next Elgible Application Cycle?", ""
                    ),
                    "Stage": meta.get("Stage", ""),
                    "Submission Year": meta.get("Submission Year", ""),
                    "Funder Notification Date": meta.get("Funder Notification Date", ""),
                    "Note(s)": meta.get("Note(s)", ""),
                    "Funder Name": meta.get("Funder Name", ""),
                    "Date Submitted": meta.get("Date Submitted", ""),
                    "Category": category_name,
                    "Approver": "",  # Timesheet-level only, unused at LSC
                    "Date unit": "Month",
                    "Date": month_key,
                    "Hours": 0.0,
                    "Grant Type": meta.get("Grant Type", ""),
                    "Outline Link": meta.get("Outline Link", ""),
                }

            agg[key]["Hours"] += entry.get("Tracked (Minutes)", 0) / 60

        # Final cleanup pass: replace any stray Nones with "". Do NOT round
        # Hours here — per-group rounding silently drifts from MonthEXACT_RAW
        # (which sums un-rounded values). Sheets will display whatever cell
        # format the column has; the underlying float keeps full precision so
        # SUM(All.Hours) == SUM(MonthEXACT_RAW.Tracked) within float epsilon.
        for row in agg.values():
            for k in list(row.keys()):
                if row[k] is None:
                    row[k] = ""

        rows = sorted(agg.values(), key=lambda r: (
            r["Person"], r["Project"], r["Category"], r["Date"]
        ))

        logger.info(
            f"Aggregated {len(daily_entries)} entries into {len(rows)} enriched "
            f"monthly rows (Person+Project+Category+Month)"
        )
        return rows

    def _build_project_metadata_lookup(
        self,
        active_data: Optional[List[Dict[str, Any]]] = None,
        archived_data: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Build a project name → metadata dict from active + archived projects.

        Used to enrich time entries with Client Name and other project fields.
        When active_data / archived_data are pre-fetched by the caller, they're
        used as-is (no extra API calls).
        """
        try:
            if active_data is None:
                active_data = self.get_projects(archived=False)
            if archived_data is None:
                archived_data = self.get_projects(archived=True)
            lookup = {}
            for p in active_data + archived_data:
                name = p.get("Project name", "")
                if name:
                    lookup[name] = p
            return lookup
        except Exception as e:
            logger.warning(f"Could not build project metadata lookup: {e}")
            return {}

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
