from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.auth import (
    AuthUser,
    create_token,
    demo_login_enabled,
    require_admin,
    require_any_scope,
    require_auth,
    require_scope,
    visible_scope_ids,
)
from app.db import migrate
from app.schemas import CancelTurnRequest, CancelTurnResponse, TurnRequest, TurnResponse
from app.record_schemas import CycleInput, IssueInput, MemberInput, ProjectInput
from app.services.agent import DemoAgent
from app.services.product_data_store import (
    InvalidReference,
    ProductDataStore,
    RecordConflict,
    RecordNotFound,
    ScopeViolation,
)

agent = DemoAgent()
product_data = ProductDataStore()


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    yield


app = FastAPI(
    title="Pixel Demo Agent API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(RecordConflict)
async def conflict_handler(_: Request, error: RecordConflict):
    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.exception_handler(RecordNotFound)
async def missing_handler(_: Request, error: RecordNotFound):
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(ScopeViolation)
async def scope_violation_handler(_: Request, error: ScopeViolation):
    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(InvalidReference)
async def invalid_reference_handler(_: Request, error: InvalidReference):
    return JSONResponse(status_code=422, content={"detail": str(error)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Unauthenticated endpoints ---


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class DemoLoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)


class DemoLoginResponse(BaseModel):
    token: str
    user_id: str


@app.post("/api/auth/demo-login", response_model=DemoLoginResponse)
def demo_login(body: DemoLoginRequest) -> DemoLoginResponse:
    if not demo_login_enabled():
        return JSONResponse(status_code=403, content={"detail": "Demo login is disabled."})
    try:
        token = create_token(body.user_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return DemoLoginResponse(token=token, user_id=body.user_id)


# --- Authenticated endpoints ---


@app.get("/api/auth/me")
def current_user(user: AuthUser = Depends(require_auth)) -> dict:
    return {"user_id": user.user_id, "scope_ids": sorted(user.scope_ids), "is_admin": user.is_admin}


@app.get("/api/demo-data")
def get_demo_data(user: AuthUser = Depends(require_auth)) -> dict[str, list[dict]]:
    return product_data.load(visible_scope_ids(user))


@app.post("/api/demo-data/reset")
def reset_demo_data(user: AuthUser = Depends(require_auth)) -> dict[str, list[dict]]:
    require_admin(user)
    return product_data.reset()


@app.post("/api/demo-data/issues")
def create_demo_issue(issue: IssueInput,
                      user: AuthUser = Depends(require_auth),
                      idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    require_any_scope(product_data.scopes_for_record(issue.projectId, issue.project), user)
    return product_data.save_issue(issue.model_dump(mode="json"), idempotency_key)


@app.put("/api/demo-data/issues/{issue_id}")
def update_demo_issue(issue_id: str, issue: IssueInput,
                      user: AuthUser = Depends(require_auth)) -> dict:
    existing = product_data.get_issue(issue_id)
    if existing is None:
        raise RecordNotFound("This ticket no longer exists.")
    # The user must be able to see the ticket now and wherever the edit moves it.
    require_any_scope(product_data.scopes_for_record(existing["projectId"], existing["project"]), user)
    require_any_scope(product_data.scopes_for_record(issue.projectId, issue.project), user)
    return product_data.update_issue(issue_id, issue.model_dump(mode="json"))


@app.post("/api/demo-data/projects")
def create_demo_project(project: ProjectInput, workspace_scope_id: str,
                        user: AuthUser = Depends(require_auth),
                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    require_scope(workspace_scope_id, user)
    return product_data.save_project(project.model_dump(mode="json"), workspace_scope_id, idempotency_key)


@app.post("/api/demo-data/cycles")
def create_demo_cycle(cycle: CycleInput,
                      user: AuthUser = Depends(require_auth),
                      idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    # Cycles without a project are workspace-wide and reserved for administrators.
    if cycle.projectId is None:
        require_admin(user)
    else:
        require_any_scope(product_data.scopes_for_record(cycle.projectId), user)
    return product_data.save_cycle(cycle.model_dump(mode="json"), idempotency_key)


@app.post("/api/demo-data/team-members")
def create_demo_team_member(member: MemberInput, workspace_scope_id: str,
                            user: AuthUser = Depends(require_auth),
                            idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    require_scope(workspace_scope_id, user)
    return product_data.save_team_member(member.model_dump(mode="json"), workspace_scope_id, idempotency_key)


@app.post("/api/turn", response_model=TurnResponse)
def create_turn(request: TurnRequest,
                user: AuthUser = Depends(require_auth)) -> TurnResponse:
    require_scope(request.workspace_scope_id, user)
    return agent.handle_turn(request, owner=user)


@app.post("/api/turn/{turn_id}/cancel", response_model=CancelTurnResponse)
def cancel_turn(turn_id: int, request: CancelTurnRequest,
                user: AuthUser = Depends(require_auth)) -> CancelTurnResponse:
    if not agent.sessions.owns_session(request.session_id, user.user_id, user.customer_id):
        raise HTTPException(status_code=404, detail="This conversation was not found.")
    cancelled = agent.cancel_turn(request.session_id, turn_id)
    return CancelTurnResponse(
        session_id=request.session_id,
        turn_id=turn_id,
        status="cancelled" if cancelled else "not_active",
    )
