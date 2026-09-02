from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.db import get_connection
from app.schemas import SessionSummary, Signal


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SessionManager:
    def ensure_session(self, session_id: str, product_id: str) -> None:
        with get_connection() as connection:
            existing = connection.execute(
                "select id from sessions where id = ?",
                (session_id,),
            ).fetchone()
            if existing:
                return

            connection.execute(
                """
                insert into sessions(id, product_id, active_turn_id, latest_turn_id, started_at)
                values (?, ?, null, null, ?)
                """,
                (session_id, product_id, utc_now()),
            )
            connection.execute(
                "insert into visitor_context(session_id) values (?)",
                (session_id,),
            )

    def activate_turn(self, session_id: str, turn_id: int) -> bool:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                update sessions
                set active_turn_id = ?, latest_turn_id = ?
                where id = ?
                  and (latest_turn_id is null or latest_turn_id < ?)
                """,
                (turn_id, turn_id, session_id, turn_id),
            )
            return cursor.rowcount == 1

    def is_active_turn(self, session_id: str, turn_id: int) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                "select active_turn_id from sessions where id = ?",
                (session_id,),
            ).fetchone()
        return bool(row and row["active_turn_id"] == turn_id)

    def cancel_turn(self, session_id: str, turn_id: int) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                "select active_turn_id from sessions where id = ?",
                (session_id,),
            ).fetchone()

            if not row or row["active_turn_id"] != turn_id:
                return False

            connection.execute(
                "update sessions set active_turn_id = null where id = ?",
                (session_id,),
            )
            return True

    def complete_turn(self, session_id: str, turn_id: int) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                update sessions
                set active_turn_id = null
                where id = ? and active_turn_id = ?
                """,
                (session_id, turn_id),
            )

    def store_message(self, session_id: str, turn_id: int, role: str, content: str) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                insert into messages(id, session_id, turn_id, role, content, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (str(uuid4()), session_id, turn_id, role, content, utc_now()),
            )

    def store_signals(self, session_id: str, turn_id: int, signals: list[Signal]) -> None:
        if not signals:
            return

        with get_connection() as connection:
            for signal in signals:
                connection.execute(
                    """
                    insert into signals(id, session_id, turn_id, type, value, confidence, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        session_id,
                        turn_id,
                        signal.type,
                        signal.value,
                        signal.confidence,
                        utc_now(),
                    ),
                )

    def remember_session_context(
        self,
        session_id: str,
        signals: list[Signal],
        clarification_pending: str | None = None,
    ) -> None:
        with get_connection() as connection:
            row = connection.execute(
                """
                select goals, pain_points, features_interested_in
                from visitor_context
                where session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return

            goals = _json_list(row["goals"])
            pain_points = _json_list(row["pain_points"])
            features = _json_list(row["features_interested_in"])

            for signal in signals:
                if signal.type == "feature_interest":
                    _append_unique(features, signal.value)
                if signal.type == "pain_point":
                    _append_unique(pain_points, signal.value)
                if signal.type == "goal":
                    _append_unique(goals, signal.value)

            connection.execute(
                """
                update visitor_context
                set goals = ?,
                    pain_points = ?,
                    features_interested_in = ?
                where session_id = ?
                """,
                (
                    json.dumps(goals),
                    json.dumps(pain_points),
                    json.dumps(features),
                    session_id,
                ),
            )

    def latest_signal_value(self, session_id: str, signal_type: str) -> str | None:
        with get_connection() as connection:
            row = connection.execute(
                """
                select value
                from signals
                where session_id = ? and type = ?
                order by created_at desc
                limit 1
                """,
                (session_id, signal_type),
            ).fetchone()
        return row["value"] if row else None

    def session_summary(
        self,
        session_id: str,
        clarification_pending: str | None = None,
    ) -> SessionSummary:
        with get_connection() as connection:
            row = connection.execute(
                """
                select goals, pain_points, features_interested_in
                from visitor_context
                where session_id = ?
                """,
                (session_id,),
            ).fetchone()

        return SessionSummary(
            interests=_json_list(row["features_interested_in"]) if row else [],
            pain_points=_json_list(row["pain_points"]) if row else [],
            last_person=self.latest_signal_value(session_id, "person_interest"),
            last_feature=self.latest_signal_value(session_id, "feature_interest"),
            clarification_pending=clarification_pending,
        )


def _json_list(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    value = json.loads(raw_value)
    return value if isinstance(value, list) else []


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
