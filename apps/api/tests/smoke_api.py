from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from app.main import app  # noqa: E402


with TestClient(app) as client:
    response = client.post(
        "/api/turn",
        json={
            "session_id": "session_smoke",
            "turn_id": 1,
            "product_id": "linear_simplified",
            "message": "We're using Jira and sprint planning is messy.",
            "input_mode": "text",
        },
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))

    cancel_response = client.post(
        "/api/turn/1/cancel",
        json={"session_id": "session_smoke"},
    )
    cancel_response.raise_for_status()
    print(json.dumps(cancel_response.json(), indent=2))
