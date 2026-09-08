from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import migrate
from app.schemas import CancelTurnRequest, CancelTurnResponse, TurnRequest, TurnResponse
from app.services.agent import DemoAgent
from app.services.product_data_store import ProductDataStore

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/demo-data")
def get_demo_data() -> dict[str, list[dict]]:
    return product_data.load()


@app.post("/api/demo-data/reset")
def reset_demo_data() -> dict[str, list[dict]]:
    return product_data.reset()


@app.post("/api/demo-data/issues")
def create_demo_issue(issue: dict) -> dict:
    return product_data.save_issue(issue)


@app.put("/api/demo-data/issues/{issue_id}")
def update_demo_issue(issue_id: str, issue: dict) -> dict:
    return product_data.update_issue(issue_id, issue)


@app.post("/api/demo-data/projects")
def create_demo_project(project: dict, workspace_scope_id: str) -> dict:
    return product_data.save_project(project, workspace_scope_id)


@app.post("/api/demo-data/cycles")
def create_demo_cycle(cycle: dict) -> dict:
    return product_data.save_cycle(cycle)


@app.post("/api/demo-data/team-members")
def create_demo_team_member(member: dict, workspace_scope_id: str) -> dict:
    return product_data.save_team_member(member, workspace_scope_id)


@app.post("/api/turn", response_model=TurnResponse)
def create_turn(request: TurnRequest) -> TurnResponse:
    return agent.handle_turn(request)


@app.post("/api/turn/{turn_id}/cancel", response_model=CancelTurnResponse)
def cancel_turn(turn_id: int, request: CancelTurnRequest) -> CancelTurnResponse:
    cancelled = agent.cancel_turn(request.session_id, turn_id)
    return CancelTurnResponse(
        session_id=request.session_id,
        turn_id=turn_id,
        status="cancelled" if cancelled else "not_active",
    )
