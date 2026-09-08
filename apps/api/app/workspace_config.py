from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceScope:
    id: str
    name: str
    description: str
    allowed_project_ids: frozenset[str]
    allowed_issue_projects: frozenset[str]
    allowed_team_members: frozenset[str]


WORKSPACE_SCOPES: tuple[WorkspaceScope, ...] = (
    WorkspaceScope(
        id="workspace-product-eng",
        name="Product Engineering Workspace",
        description="Scoped to Integrations and Issue Triage project work.",
        allowed_project_ids=frozenset({"PRJ-101", "PRJ-102"}),
        allowed_issue_projects=frozenset({"Integrations", "Issue Triage"}),
        allowed_team_members=frozenset({"Maya Chen", "Noah Patel"}),
    ),
    WorkspaceScope(
        id="workspace-platform",
        name="Platform Workspace",
        description="Scoped to planning insights, migration work, and platform reliability.",
        allowed_project_ids=frozenset({"PRJ-103", "PRJ-104"}),
        allowed_issue_projects=frozenset({"Planning", "Migration"}),
        allowed_team_members=frozenset({"Avery Brooks", "Iris Morgan"}),
    ),
)

WORKSPACE_SCOPES_BY_ID = {scope.id: scope for scope in WORKSPACE_SCOPES}
DEFAULT_WORKSPACE_SCOPE_ID = "workspace-product-eng"
