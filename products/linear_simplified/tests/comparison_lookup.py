"""A read-only, workspace-scoped record lookup over the demo seed data, for comparison tests only.

Scope is applied before anything else: records and people outside the workspace are never
matched, counted or offered. The real Linear lookup arrives in 3.2 slice 3.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.engine.lookup import PeopleMatch, PersonView, RecordView  # noqa: E402
from app.services.product_data_store import SEED_PROJECTS, SEED_TEAM  # noqa: E402
from app.workspace_config import WORKSPACE_SCOPES_BY_ID  # noqa: E402

ISSUES = json.loads((REPO_ROOT / "packages" / "shared" / "demo-data" / "issues.json").read_text(encoding="utf-8"))


def person_id(name: str) -> str:
    return name.lower().replace(" ", "-")


class LinearComparisonLookup:
    def __init__(self, workspace_scope_id: str) -> None:
        scope = WORKSPACE_SCOPES_BY_ID[workspace_scope_id]
        self._projects = frozenset(scope.allowed_project_ids)

    def _records(self, entity: str) -> list[RecordView]:
        if entity == "project":
            return [
                RecordView("project", p["id"], p["name"], {"lead": person_id(p["lead"])})
                for p in SEED_PROJECTS if p["id"] in self._projects
            ]
        if entity == "issue":
            return [
                RecordView("issue", i["id"], i["title"], {
                    "assignee": person_id(i["assignee"]), "priority": i["priority"],
                    "status": i["status"], "project": i["projectId"],
                })
                for i in ISSUES if i["projectId"] in self._projects
            ]
        if entity == "member":
            return [
                RecordView("member", person_id(m["name"]), m["name"], {"projects": tuple(m["projectIds"])})
                for m in SEED_TEAM if self._projects.intersection(m["projectIds"])
            ]
        return []

    def get(self, entity: str, record_id: str) -> RecordView | None:
        return next((r for r in self._records(entity) if r.id.lower() == record_id.lower()), None)

    def search(self, entity: str, text: str, limit: int) -> list[RecordView]:
        needle = text.lower()
        return [r for r in self._records(entity) if needle in r.title.lower()][:limit]

    def by_person(self, entity: str, person: str, limit: int) -> list[RecordView]:
        field = {"issue": "assignee", "project": "lead"}.get(entity)
        return [r for r in self._records(entity) if field and r.fields.get(field) == person][:limit]

    def people(self, text: str, limit: int) -> PeopleMatch:
        wanted = text.lower().split()
        matches = tuple(
            PersonView(r.id, r.title) for r in self._records("member")
            if wanted and (r.title.lower().split() == wanted
                           or (len(wanted) == 1 and wanted[0] in r.title.lower().split()))
        )
        return PeopleMatch(matches[:limit])

    def count(self, entity: str) -> int:
        return len(self._records(entity))
