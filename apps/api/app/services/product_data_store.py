from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db import get_connection
from app.workspace_config import WORKSPACE_SCOPES


API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
ISSUES_PATH = REPO_ROOT / "packages" / "shared" / "demo-data" / "issues.json"


SEED_PROJECTS: tuple[dict[str, Any], ...] = (
    {
        "id": "PRJ-101",
        "name": "GitHub Integration Hardening",
        "description": "Improve PR sync reliability, webhook recovery, and commit-to-issue visibility.",
        "progress": 68,
        "status": "Active",
        "lead": "Maya Chen",
        "team": "Product Engineering",
        "targetDate": "2026-09-28",
    },
    {
        "id": "PRJ-102",
        "name": "Issue Triage Workflow",
        "description": "Reduce duplicate reports and speed up assignment, priority, and status updates.",
        "progress": 54,
        "status": "Active",
        "lead": "Noah Patel",
        "team": "Product Engineering",
        "targetDate": "2026-10-12",
    },
    {
        "id": "PRJ-103",
        "name": "Cycle Planning Insights",
        "description": "Forecast sprint capacity, burndown risks, and planning accuracy.",
        "progress": 42,
        "status": "At risk",
        "lead": "Avery Brooks",
        "team": "Platform",
        "targetDate": "2026-09-18",
    },
    {
        "id": "PRJ-104",
        "name": "Workspace Migration",
        "description": "Move archived project history into the new operating model.",
        "progress": 31,
        "status": "Planned",
        "lead": "Iris Morgan",
        "team": "Platform",
        "targetDate": "2026-11-04",
    },
)

SEED_TEAM: tuple[dict[str, Any], ...] = (
    {
        "name": "Maya Chen",
        "initials": "MC",
        "role": "Frontend Lead",
        "load": 84,
        "projectIds": ["PRJ-101"],
    },
    {
        "name": "Noah Patel",
        "initials": "NP",
        "role": "Product Engineer",
        "load": 71,
        "projectIds": ["PRJ-102"],
    },
    {
        "name": "Avery Brooks",
        "initials": "AB",
        "role": "Engineering Manager",
        "load": 63,
        "projectIds": ["PRJ-103"],
    },
    {
        "name": "Iris Morgan",
        "initials": "IM",
        "role": "Platform Engineer",
        "load": 77,
        "projectIds": ["PRJ-104"],
    },
)

SEED_CYCLES: tuple[dict[str, Any], ...] = (
    {
        "id": "CYC-14",
        "name": "Product Engineering Cycle 14",
        "projectId": "PRJ-101",
        "daysLeft": 8,
        "progress": 68,
        "completed": 18,
        "inProgress": 9,
        "remaining": 11,
        "focus": ["Bug triage", "Cycle planning", "GitHub sync", "Assignment flow"],
        "status": "Active",
        "team": "Product Engineering",
        "startDate": "2026-08-24",
        "endDate": "2026-09-08",
    },
    {
        "id": "CYC-21",
        "name": "Platform Cycle 21",
        "projectId": "PRJ-103",
        "daysLeft": 6,
        "progress": 42,
        "completed": 7,
        "inProgress": 6,
        "remaining": 9,
        "focus": ["Capacity forecast", "Migration readiness", "Planning accuracy"],
        "status": "Active",
        "team": "Platform",
        "startDate": "2026-08-31",
        "endDate": "2026-09-14",
    },
)


class ProductDataStore:
    def load(self) -> dict[str, list[dict[str, Any]]]:
        self.seed_if_empty()
        with get_connection() as connection:
            return {
                "workspaceScopes": [
                    _scope_from_row(row)
                    for row in connection.execute(
                        "select * from demo_workspace_scopes order by id"
                    ).fetchall()
                ],
                "projects": [
                    _project_from_row(row)
                    for row in connection.execute(
                        "select * from demo_projects order by id"
                    ).fetchall()
                ],
                "team": [
                    _member_from_row(row)
                    for row in connection.execute(
                        "select * from demo_team_members order by name"
                    ).fetchall()
                ],
                "cycles": [
                    _cycle_from_row(row)
                    for row in connection.execute(
                        "select * from demo_cycles order by id"
                    ).fetchall()
                ],
                "issues": [
                    _issue_from_row(row)
                    for row in connection.execute(
                        "select * from demo_issues order by id"
                    ).fetchall()
                ],
            }

    def seed_if_empty(self) -> None:
        with get_connection() as connection:
            row = connection.execute("select count(*) as count from demo_projects").fetchone()
            if row and row["count"] > 0:
                return
        self.reset()

    def reset(self) -> dict[str, list[dict[str, Any]]]:
        from app.services.action_planner import ActionPlanner

        ActionPlanner.reset_created_count()
        issues = json.loads(ISSUES_PATH.read_text(encoding="utf-8"))
        with get_connection() as connection:
            connection.executescript(
                """
                delete from demo_issues;
                delete from demo_cycles;
                delete from demo_team_members;
                delete from demo_projects;
                delete from demo_workspace_scopes;
                """
            )

            for scope in WORKSPACE_SCOPES:
                connection.execute(
                    """
                    insert into demo_workspace_scopes(
                      id, name, description, allowed_project_ids, allowed_issue_projects
                    )
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        scope.id,
                        scope.name,
                        scope.description,
                        json.dumps(sorted(scope.allowed_project_ids)),
                        json.dumps(sorted(scope.allowed_issue_projects)),
                    ),
                )
            for project in SEED_PROJECTS:
                self._upsert_project(connection, project)
            for member in SEED_TEAM:
                self._upsert_member(connection, member)
            for cycle in SEED_CYCLES:
                self._upsert_cycle(connection, cycle)
            for issue in issues:
                self._upsert_issue(connection, issue)

        return self.load()

    def save_issue(self, issue: dict[str, Any]) -> dict[str, Any]:
        self.seed_if_empty()
        with get_connection() as connection:
            self._upsert_issue(connection, issue)
        return issue

    def update_issue(self, issue_id: str, issue: dict[str, Any]) -> dict[str, Any]:
        self.seed_if_empty()
        issue = {**issue, "id": issue_id}
        with get_connection() as connection:
            self._upsert_issue(connection, issue)
        return issue

    def save_project(self, project: dict[str, Any], workspace_scope_id: str) -> dict[str, Any]:
        self.seed_if_empty()
        with get_connection() as connection:
            self._upsert_project(connection, project)
            _add_project_to_scope(connection, workspace_scope_id, project)
        return project

    def save_cycle(self, cycle: dict[str, Any]) -> dict[str, Any]:
        self.seed_if_empty()
        with get_connection() as connection:
            self._upsert_cycle(connection, cycle)
        return cycle

    def save_team_member(
        self,
        member: dict[str, Any],
        workspace_scope_id: str,
    ) -> dict[str, Any]:
        self.seed_if_empty()
        with get_connection() as connection:
            scope = connection.execute(
                "select allowed_project_ids from demo_workspace_scopes where id = ?",
                (workspace_scope_id,),
            ).fetchone()
            project_ids = member.get("projectIds") or []
            if not project_ids and scope:
                project_ids = json.loads(scope["allowed_project_ids"])
            member = {**member, "projectIds": project_ids}
            self._upsert_member(connection, member)
        return member

    def _upsert_issue(self, connection, issue: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into demo_issues(
              id, title, priority, assignee, project, project_id, status, cycle,
              estimate, label, description
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
              title = excluded.title,
              priority = excluded.priority,
              assignee = excluded.assignee,
              project = excluded.project,
              project_id = excluded.project_id,
              status = excluded.status,
              cycle = excluded.cycle,
              estimate = excluded.estimate,
              label = excluded.label,
              description = excluded.description
            """,
            (
                issue["id"],
                issue["title"],
                issue["priority"],
                issue["assignee"],
                issue["project"],
                issue.get("projectId"),
                issue["status"],
                issue.get("cycle"),
                issue.get("estimate"),
                issue.get("label"),
                issue.get("description"),
            ),
        )

    def _upsert_project(self, connection, project: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into demo_projects(
              id, name, description, progress, status, lead, team, target_date
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
              name = excluded.name,
              description = excluded.description,
              progress = excluded.progress,
              status = excluded.status,
              lead = excluded.lead,
              team = excluded.team,
              target_date = excluded.target_date
            """,
            (
                project["id"],
                project["name"],
                project["description"],
                int(project["progress"]),
                project["status"],
                project["lead"],
                project["team"],
                project["targetDate"],
            ),
        )

    def _upsert_member(self, connection, member: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into demo_team_members(name, initials, role, load, email, project_ids)
            values (?, ?, ?, ?, ?, ?)
            on conflict(name) do update set
              initials = excluded.initials,
              role = excluded.role,
              load = excluded.load,
              email = excluded.email,
              project_ids = excluded.project_ids
            """,
            (
                member["name"],
                member["initials"],
                member["role"],
                int(member["load"]),
                member.get("email"),
                json.dumps(member.get("projectIds", [])),
            ),
        )

    def _upsert_cycle(self, connection, cycle: dict[str, Any]) -> None:
        connection.execute(
            """
            insert into demo_cycles(
              id, name, project_id, days_left, progress, completed, in_progress,
              remaining, focus, status, team, start_date, end_date
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
              name = excluded.name,
              project_id = excluded.project_id,
              days_left = excluded.days_left,
              progress = excluded.progress,
              completed = excluded.completed,
              in_progress = excluded.in_progress,
              remaining = excluded.remaining,
              focus = excluded.focus,
              status = excluded.status,
              team = excluded.team,
              start_date = excluded.start_date,
              end_date = excluded.end_date
            """,
            (
                cycle["id"],
                cycle["name"],
                cycle.get("projectId"),
                int(cycle["daysLeft"]),
                int(cycle["progress"]),
                int(cycle["completed"]),
                int(cycle["inProgress"]),
                int(cycle["remaining"]),
                json.dumps(cycle.get("focus", [])),
                cycle["status"],
                cycle["team"],
                cycle["startDate"],
                cycle["endDate"],
            ),
        )


def _scope_from_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "allowedProjectIds": json.loads(row["allowed_project_ids"]),
        "allowedIssueProjects": json.loads(row["allowed_issue_projects"]),
    }


def _project_from_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "progress": row["progress"],
        "status": row["status"],
        "lead": row["lead"],
        "team": row["team"],
        "targetDate": row["target_date"],
    }


def _member_from_row(row) -> dict[str, Any]:
    return {
        "name": row["name"],
        "initials": row["initials"],
        "role": row["role"],
        "load": row["load"],
        "email": row["email"],
        "projectIds": json.loads(row["project_ids"]),
    }


def _cycle_from_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "projectId": row["project_id"],
        "daysLeft": row["days_left"],
        "progress": row["progress"],
        "completed": row["completed"],
        "inProgress": row["in_progress"],
        "remaining": row["remaining"],
        "focus": json.loads(row["focus"]),
        "status": row["status"],
        "team": row["team"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
    }


def _issue_from_row(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "priority": row["priority"],
        "assignee": row["assignee"],
        "project": row["project"],
        "projectId": row["project_id"],
        "status": row["status"],
        "cycle": row["cycle"],
        "estimate": row["estimate"],
        "label": row["label"],
        "description": row["description"],
    }


def _add_project_to_scope(connection, workspace_scope_id: str, project: dict[str, Any]) -> None:
    row = connection.execute(
        "select allowed_project_ids, allowed_issue_projects from demo_workspace_scopes where id = ?",
        (workspace_scope_id,),
    ).fetchone()
    if not row:
        return

    project_ids = json.loads(row["allowed_project_ids"])
    issue_projects = json.loads(row["allowed_issue_projects"])
    if project["id"] not in project_ids:
        project_ids.append(project["id"])
    if project["name"] not in issue_projects:
        issue_projects.append(project["name"])

    connection.execute(
        """
        update demo_workspace_scopes
        set allowed_project_ids = ?, allowed_issue_projects = ?
        where id = ?
        """,
        (json.dumps(project_ids), json.dumps(issue_projects), workspace_scope_id),
    )
