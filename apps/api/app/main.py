from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from app.auth import (
    AuthUser,
    create_token,
    create_visitor_token,
    demo_login_enabled,
    require_admin,
    require_any_scope,
    require_auth,
    require_member,
    require_org_admin,
    require_scope,
    visible_scope_ids,
)
from app.definitions.access import AccessDenied, authorize_product
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
from app.services.speech_service import SpeechService, SpeechUnavailable
from app.services.usage_ledger import UsageLedger
from app.product_config import PRODUCTS_BY_ID
from app.tenancy import deployment_id

agent = DemoAgent()
product_data = ProductDataStore()
usage = UsageLedger()
speech_service = SpeechService(usage)


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
    tenant_id: str


@app.post("/api/auth/demo-login", response_model=DemoLoginResponse)
def demo_login(body: DemoLoginRequest) -> DemoLoginResponse:
    if not demo_login_enabled():
        return JSONResponse(status_code=403, content={"detail": "Demo login is disabled."})
    organizations = agent.directory.organizations_of(body.user_id)
    if len(organizations) != 1:
        return JSONResponse(status_code=404, content={"detail": "Unknown demo user."})
    tenant_id = organizations[0]
    token = create_token(body.user_id, tenant_id)
    return DemoLoginResponse(token=token, user_id=body.user_id, tenant_id=tenant_id)


class VisitorSessionResponse(BaseModel):
    token: str
    visitor_id: str
    tenant_id: str
    product_id: str


@app.post(
    "/api/organizations/{tenant_id}/products/{product_id}/visitor-sessions",
    response_model=VisitorSessionResponse,
)
def start_visitor_session(tenant_id: str, product_id: str) -> VisitorSessionResponse:
    """A visitor session is scoped to one product and grants nothing else."""
    try:
        token, visitor_id = create_visitor_token(tenant_id, product_id)
    except AccessDenied:
        # One answer for unknown, private, disabled and suspended alike.
        raise HTTPException(status_code=404, detail="This product is not available.")
    return VisitorSessionResponse(token=token, visitor_id=visitor_id, tenant_id=tenant_id, product_id=product_id)


# --- Authenticated endpoints ---


@app.get("/api/demo-data")
def get_demo_data(user: AuthUser = Depends(require_member)) -> dict[str, list[dict]]:
    return product_data.load(visible_scope_ids(user))


@app.post("/api/demo-data/reset")
def reset_demo_data(user: AuthUser = Depends(require_member)) -> dict[str, list[dict]]:
    require_admin(user)
    return product_data.reset()


@app.post("/api/demo-data/issues")
def create_demo_issue(issue: IssueInput,
                      user: AuthUser = Depends(require_member),
                      idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    require_any_scope(product_data.scopes_for_record(issue.projectId, issue.project), user)
    return product_data.save_issue(issue.model_dump(mode="json"), idempotency_key)


@app.put("/api/demo-data/issues/{issue_id}")
def update_demo_issue(issue_id: str, issue: IssueInput,
                      user: AuthUser = Depends(require_member)) -> dict:
    existing = product_data.get_issue(issue_id)
    if existing is None:
        raise RecordNotFound("This ticket no longer exists.")
    # The user must be able to see the ticket now and wherever the edit moves it.
    require_any_scope(product_data.scopes_for_record(existing["projectId"], existing["project"]), user)
    require_any_scope(product_data.scopes_for_record(issue.projectId, issue.project), user)
    return product_data.update_issue(issue_id, issue.model_dump(mode="json"))


@app.post("/api/demo-data/projects")
def create_demo_project(project: ProjectInput, workspace_scope_id: str,
                        user: AuthUser = Depends(require_member),
                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    require_scope(workspace_scope_id, user)
    return product_data.save_project(project.model_dump(mode="json"), workspace_scope_id, idempotency_key)


@app.post("/api/demo-data/cycles")
def create_demo_cycle(cycle: CycleInput,
                      user: AuthUser = Depends(require_member),
                      idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    # Cycles without a project are workspace-wide and reserved for administrators.
    if cycle.projectId is None:
        require_admin(user)
    else:
        require_any_scope(product_data.scopes_for_record(cycle.projectId), user)
    return product_data.save_cycle(cycle.model_dump(mode="json"), idempotency_key)


@app.post("/api/demo-data/team-members")
def create_demo_team_member(member: MemberInput, workspace_scope_id: str,
                            user: AuthUser = Depends(require_member),
                            idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    require_scope(workspace_scope_id, user)
    return product_data.save_team_member(member.model_dump(mode="json"), workspace_scope_id, idempotency_key)


# --- Paid-provider capabilities (the API is the only component that calls providers) ---


class SpeechRequest(BaseModel):
    model_config = {"extra": "forbid"}

    text: str = Field(min_length=1, max_length=2000)
    product_id: str = Field(min_length=1, max_length=64)
    session_id: str | None = Field(default=None, max_length=100)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text cannot be blank")
        return stripped


@app.post("/api/speech", response_class=Response)
def synthesize_speech(body: SpeechRequest, user: AuthUser = Depends(require_auth)) -> Response:
    try:
        access = authorize_product(user, body.product_id, agent.directory)
    except AccessDenied:
        raise HTTPException(status_code=404, detail="This product is not available.")
    # A session is attributed only when it belongs to the caller and to this product.
    session_id = body.session_id
    if session_id:
        pin = agent.sessions.pin_for(session_id)
        if (
            pin is None
            or pin.product_id != body.product_id
            or not agent.sessions.owns_session(session_id, user.user_id, user.tenant_id)
        ):
            session_id = None
    voice_style = PRODUCTS_BY_ID[access.binding.definition_id].voice_style
    try:
        speech = speech_service.synthesize(
            tenant=access.context,
            voice_style=voice_style,
            user_id=user.user_id,
            session_id=session_id,
            text=body.text,
        )
    except SpeechUnavailable as unavailable:
        return JSONResponse(
            status_code=unavailable.status_code,
            content={"detail": "Neural voice is unavailable right now.", "reason": unavailable.reason},
        )
    headers = {"Cache-Control": "private, no-store", "X-TTS-Engine": speech.engine}
    if speech.voice:
        headers["X-TTS-Voice"] = speech.voice
    return Response(content=speech.audio, media_type=speech.media_type, headers=headers)


@app.get("/api/usage/summary")
def usage_summary(day: str | None = None, user: AuthUser = Depends(require_member)) -> dict:
    """Usage for the caller's organization, by owning team and product. Organization admins only."""
    require_org_admin(user)
    return {
        "tenant_id": user.tenant_id,
        "deployment_id": deployment_id(),
        "rows": usage.organization_summary(user.tenant_id, deployment_id(), day),
    }


@app.post("/api/turn", response_model=TurnResponse)
def create_turn(request: TurnRequest,
                user: AuthUser = Depends(require_auth)) -> TurnResponse:
    require_scope(request.workspace_scope_id, user)
    return agent.handle_turn(request, user)


@app.post("/api/turn/{turn_id}/cancel", response_model=CancelTurnResponse)
def cancel_turn(turn_id: int, request: CancelTurnRequest,
                user: AuthUser = Depends(require_auth)) -> CancelTurnResponse:
    if not agent.sessions.owns_session(request.session_id, user.user_id, user.tenant_id):
        raise HTTPException(status_code=404, detail="This conversation was not found.")
    cancelled = agent.cancel_turn(request.session_id, turn_id)
    return CancelTurnResponse(
        session_id=request.session_id,
        turn_id=turn_id,
        status="cancelled" if cancelled else "not_active",
    )
