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
    demo_identity_allowed,
    demo_login_enabled,
    product_record_grant,
    require_any_scope,
    require_auth,
    require_member,
    require_org_admin,
    require_record_access,
    require_record_admin,
    require_scope,
)
from app.definitions.access import AccessDenied, ProductAccess, authorize_product
from app.definitions.integrity import ReadinessCheck
from app.definitions.sessions import DefinitionUnavailable, SessionEnded, check_pinned_session, pin_new_session
from app.db import get_connection, migrate
from app.engine.execution import ExecutionRefused
from app.record_access import RecordGrant, legacy_record_owner
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
from app.services.rate_limit import RateLimiter
from app.services.record_writes import KeyedWriter, RecordChange, require_visible_scope
from app.services.speech_service import SpeechService, SpeechUnavailable
from app.services.env import env_bool
from app.services.usage_ledger import UsageLedger
from app.product_config import PRODUCTS_BY_ID
from app.tenancy import deployment_id

agent = DemoAgent()
product_data = ProductDataStore()
usage = UsageLedger()
speech_service = SpeechService(usage)
keyed_writes = KeyedWriter()
readiness = ReadinessCheck()
# Armed at startup (see `lifespan`), so tests that never start the server are not throttled.
rate_limits = RateLimiter()



@asynccontextmanager
async def lifespan(_: FastAPI):
    was_armed = rate_limits.armed
    migrate()
    rate_limits.arm()
    try:
        if env_bool("PIXEL_DEMO_SEEDS", default=False):
            # Demo records are created once, at startup, and never by a request: a refused or
            # unauthorized request must leave product data exactly as it found it.
            product_data.seed_if_empty()
        yield
    finally:
        # A TestClient owns only the lifecycle state it started. Production remains armed until
        # process shutdown; a temporary test server must not throttle later direct-app tests.
        if not was_armed:
            rate_limits.disarm()


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


@app.exception_handler(ExecutionRefused)
async def execution_refused_handler(_: Request, error: ExecutionRefused):
    # A key that cannot be used is a conflict; a caller whose standing changed is a 403.
    return JSONResponse(status_code=409 if error.conflict else 403, content={"detail": error.reason})


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
@app.get("/api/health")
def health():
    # Readiness includes storage. A process that cannot open its persistent database must not be
    # advertised to the web app as healthy.
    with get_connection() as connection:
        connection.execute("select 1").fetchone()
    # Readiness also includes being able to start a conversation. A backend that answers every
    # turn with "not available" is not healthy, however well its database opens.
    problems = readiness.problems()
    if problems:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reason": "sessions_cannot_start", "products": len(problems)},
        )
    return {"status": "ok"}


class DemoLoginRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=200)


class DemoLoginResponse(BaseModel):
    token: str
    user_id: str
    tenant_id: str


@app.post("/api/auth/demo-login", response_model=DemoLoginResponse)
def demo_login(body: DemoLoginRequest, http: Request) -> DemoLoginResponse:
    rate_limits.enforce("login", http)
    if not demo_login_enabled():
        return JSONResponse(status_code=403, content={"detail": "Demo login is disabled."})
    organizations = agent.directory.organizations_of(body.user_id)
    # One answer for unknown users and for identities the demo may not issue, so the endpoint
    # never confirms that an administrator exists.
    if len(organizations) != 1 or not demo_identity_allowed(body.user_id, organizations[0]):
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
def start_visitor_session(tenant_id: str, product_id: str, http: Request) -> VisitorSessionResponse:
    """A visitor session is scoped to one product and grants nothing else."""
    rate_limits.enforce("login", http)
    try:
        token, visitor_id = create_visitor_token(tenant_id, product_id)
    except AccessDenied:
        # One answer for unknown, private, disabled and suspended alike.
        raise HTTPException(status_code=404, detail="This product is not available.")
    return VisitorSessionResponse(token=token, visitor_id=visitor_id, tenant_id=tenant_id, product_id=product_id)


# --- Authenticated endpoints ---


# Legacy record endpoints serve only the designated record-owning product (until step 3.5).


@app.get("/api/demo-data")
def get_demo_data(grant: RecordGrant = Depends(require_record_access)) -> dict[str, list[dict]]:
    return product_data.load(grant.visible_scope_ids())


@app.post("/api/demo-data/reset")
def reset_demo_data(http: Request, user: AuthUser = Depends(require_member),
                    grant: RecordGrant = Depends(require_record_access)) -> dict[str, list[dict]]:
    """Resets everyone's demo data, so it belongs to a record administrator only.

    The public demo identity is never one (see `demo_identity_allowed`); operators reset from the
    server with `python -m app.ops reset-demo-data`.
    """
    rate_limits.enforce("reset", http, identity=user.user_id)
    require_record_admin(grant)
    return product_data.reset()


@app.post("/api/demo-data/issues")
def create_demo_issue(issue: IssueInput,
                      http: Request,
                      user: AuthUser = Depends(require_member),
                      idempotency_key: str | None = Header(default=None, max_length=200),
                      x_execution_key: str | None = Header(default=None, max_length=200),
                      x_session_id: str | None = Header(default=None, max_length=100)) -> dict:
    rate_limits.enforce("write", http, identity=user.user_id)
    payload = issue.model_dump(mode="json")
    if x_execution_key:
        _refuse_legacy_idempotency(idempotency_key)
        # No legacy request key reaches the store: a second mechanism could report an older
        # receipt as this action's outcome, so the execution key is the only one.
        return _keyed(x_execution_key, x_session_id, user, ["create_issue", payload],
                      lambda product_id: _create_issue(payload, None, user, product_id))
    grant = require_record_access(user)
    require_any_scope(product_data.scopes_for_record(issue.projectId, issue.project), grant)
    return product_data.save_issue(payload, idempotency_key)


@app.put("/api/demo-data/issues/{issue_id}")
def update_demo_issue(issue_id: str, issue: IssueInput,
                      http: Request,
                      user: AuthUser = Depends(require_member),
                      x_execution_key: str | None = Header(default=None, max_length=200),
                      x_session_id: str | None = Header(default=None, max_length=100)) -> dict:
    rate_limits.enforce("write", http, identity=user.user_id)
    payload = issue.model_dump(mode="json")
    if x_execution_key:
        return _keyed(x_execution_key, x_session_id, user, ["update_issue", issue_id, payload],
                      lambda product_id: _update_issue(issue_id, payload, user, product_id))
    grant = require_record_access(user)
    existing = product_data.get_issue(issue_id)
    if existing is None:
        raise RecordNotFound("This ticket no longer exists.")
    # The user must be able to see the ticket now and wherever the edit moves it.
    require_any_scope(product_data.scopes_for_record(existing["projectId"], existing["project"]), grant)
    require_any_scope(product_data.scopes_for_record(issue.projectId, issue.project), grant)
    return product_data.update_issue(issue_id, payload)


def _create_issue(issue: dict, idempotency_key: str | None, user: AuthUser, product_id: str):
    """The change a create key authorizes, run inside the keyed write's transaction."""
    def apply(connection, grant: RecordGrant) -> RecordChange:
        _require_record_owner(connection, user, product_id)
        scopes = product_data.scopes_for_record(issue.get("projectId"), issue.get("project"),
                                                connection=connection)
        require_visible_scope(scopes, grant)
        record = product_data.save_issue(issue, idempotency_key, connection=connection)
        return RecordChange(record["id"], "created", record)

    return apply


def _update_issue(issue_id: str, issue: dict, user: AuthUser, product_id: str):
    """The change an update key authorizes; the ticket must be visible now and after the change."""
    def apply(connection, grant: RecordGrant) -> RecordChange:
        _require_record_owner(connection, user, product_id)
        existing = product_data.get_issue(issue_id, connection=connection)
        if existing is None:
            raise RecordNotFound("This ticket no longer exists.")
        for project_id, project in ((existing["projectId"], existing["project"]),
                                    (issue.get("projectId"), issue.get("project"))):
            require_visible_scope(
                product_data.scopes_for_record(project_id, project, connection=connection), grant
            )
        record = product_data.update_issue(issue_id, issue, connection=connection)
        return RecordChange(issue_id, "updated", record)

    return apply


def _reload_issue(connection, grant: RecordGrant, issue_id: str) -> dict | None:
    """Read one ticket for a replay, under the access the caller has right now."""
    record = product_data.get_issue(issue_id, connection=connection)
    if record is None:
        return None
    scopes = product_data.scopes_for_record(record["projectId"], record["project"],
                                            connection=connection)
    return record if grant.may_use_any(scopes) else None


def _refuse_legacy_idempotency(idempotency_key: str | None) -> None:
    """A keyed write must not also carry the legacy retry header.

    The header selects a stored receipt inside the record store, which would let a dispatched
    action settle as `executed` while nothing was created. One action, one key, one outcome.
    """
    if idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="An execution key is the only idempotency mechanism for an assistant write.",
        )


def _require_record_owner(connection, user: AuthUser, product_id: str) -> None:
    """Inside the transaction: these records must still belong to this organization's product."""
    owner = legacy_record_owner(connection)
    if owner is None or (owner.tenant_id, owner.product_id) != (user.tenant_id, product_id):
        raise ExecutionRefused("record_access_withdrawn", conflict=False)


def _keyed(execution_key: str, session_id: str | None, user: AuthUser, request: list, build) -> dict:
    """Perform a record write under a one-time execution key, re-checking everything first."""
    if not session_id:
        # Without the conversation, the session's definition pin cannot be re-checked.
        raise ExecutionRefused("session_not_usable", conflict=False)
    # Nothing here creates reference data. Seeding belongs to the deployment bootstrap, so a
    # refused or unauthorized request can never change product data (see `load_demo_seeds`).
    owner = legacy_record_owner()
    if owner is None or owner.tenant_id != user.tenant_id:
        raise ExecutionRefused("record_access_withdrawn", conflict=False)
    return keyed_writes.write(
        build(owner.product_id), execution_key=execution_key, principal=user,
        product_id=owner.product_id, session_id=session_id, request=request,
        reload=_reload_issue,
    )


@app.post("/api/demo-data/projects")
def create_demo_project(project: ProjectInput, workspace_scope_id: str,
                        http: Request,
                        user: AuthUser = Depends(require_member),
                        grant: RecordGrant = Depends(require_record_access),
                        idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    rate_limits.enforce("write", http, identity=user.user_id)
    require_scope(workspace_scope_id, grant)
    return product_data.save_project(project.model_dump(mode="json"), workspace_scope_id, idempotency_key)


@app.post("/api/demo-data/cycles")
def create_demo_cycle(cycle: CycleInput,
                      http: Request,
                      user: AuthUser = Depends(require_member),
                      grant: RecordGrant = Depends(require_record_access),
                      idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    rate_limits.enforce("write", http, identity=user.user_id)
    # Cycles without a project are workspace-wide and reserved for record administrators.
    if cycle.projectId is None:
        require_record_admin(grant)
    else:
        require_any_scope(product_data.scopes_for_record(cycle.projectId), grant)
    return product_data.save_cycle(cycle.model_dump(mode="json"), idempotency_key)


@app.post("/api/demo-data/team-members")
def create_demo_team_member(member: MemberInput, workspace_scope_id: str,
                            http: Request,
                            user: AuthUser = Depends(require_member),
                            grant: RecordGrant = Depends(require_record_access),
                            idempotency_key: str | None = Header(default=None, max_length=200)) -> dict:
    rate_limits.enforce("write", http, identity=user.user_id)
    require_scope(workspace_scope_id, grant)
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
def synthesize_speech(body: SpeechRequest, http: Request,
                      user: AuthUser = Depends(require_auth)) -> Response:
    """Every check runs before any budget is reserved or any provider is contacted."""
    rate_limits.enforce("speech", http, identity=user.user_id)
    try:
        access = authorize_product(user, body.product_id, agent.directory)
    except AccessDenied:
        raise HTTPException(status_code=404, detail="This product is not available.")
    try:
        definition_id = _speech_definition(user, access, body.session_id)
        speech = speech_service.synthesize(
            tenant=access.context,
            voice_style=PRODUCTS_BY_ID[definition_id].voice_style,
            user_id=user.user_id,
            session_id=body.session_id,
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


def _speech_definition(user: AuthUser, access: ProductAccess, session_id: str | None) -> str:
    """The definition speech runs on, after the same lifecycle checks a chat turn applies.

    With a session, it must belong to the caller and to this product, and still be valid on its
    pinned definition: a retired version still serves its sessions, a revoked one does not.
    Without a session, the current definition of the product must be startable. A supplied
    session is never silently ignored.
    """
    if session_id is None:
        try:
            return pin_new_session(access, agent.directory.definitions).definition_id
        except DefinitionUnavailable as unavailable:
            raise SpeechUnavailable(409, unavailable.reason) from unavailable
    pin = agent.sessions.pin_for(session_id)
    if not agent.sessions.owns_session(session_id, user.user_id, user.tenant_id) or (
        pin is not None and pin.product_id != access.binding.product_id
    ):
        raise HTTPException(status_code=404, detail="This conversation was not found.")
    try:
        return check_pinned_session(pin, agent.directory).definition_id
    except SessionEnded as ended:
        raise SpeechUnavailable(409, ended.reason) from ended


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
def create_turn(request: TurnRequest, http: Request,
                user: AuthUser = Depends(require_auth)) -> TurnResponse:
    rate_limits.enforce("turn", http, identity=user.user_id)
    try:
        authorize_product(user, request.product_id, agent.directory)
    except AccessDenied:
        # The agent answers with the same denial every unusable product gets.
        return agent.handle_turn(request, user)
    require_scope(request.workspace_scope_id, product_record_grant(user, request.product_id))
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
