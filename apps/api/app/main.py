from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import migrate
from app.schemas import CancelTurnRequest, CancelTurnResponse, TurnRequest, TurnResponse
from app.services.agent import DemoAgent

agent = DemoAgent()


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
