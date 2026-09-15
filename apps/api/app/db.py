from __future__ import annotations

import sqlite3
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
API_DIR = APP_DIR.parent
DATA_DIR = API_DIR / "data"
DB_PATH = Path(os.environ.get("PIXEL_DB_PATH", str(DATA_DIR / "demo_agent.sqlite3")))


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma busy_timeout = 10000")
    connection.execute("pragma foreign_keys = on")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def migrate() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            pragma journal_mode = wal;

            create table if not exists access_grants(
              user_id text primary key,
              scope_ids text not null,
              is_admin integer not null default 0
            );
            create table if not exists login_sessions(
              token_hash text primary key,
              user_id text not null references access_grants(user_id) on delete cascade,
              customer_id text not null,
              expires_at real not null
            );
            create table if not exists conversation_owners(
              session_id text primary key,
              user_id text not null,
              customer_id text not null,
              product_id text not null,
              scope_id text not null
            );

            create table if not exists mutation_receipts(
              request_key text primary key,
              request_body text not null,
              response_body text not null
            );

            create table if not exists sessions(
              id text primary key,
              product_id text not null,
              active_turn_id integer,
              latest_turn_id integer,
              started_at text not null,
              ended_at text
            );

            create table if not exists messages(
              id text primary key,
              session_id text not null,
              turn_id integer not null,
              role text not null,
              content text not null,
              created_at text not null
            );

            create table if not exists visitor_context(
              session_id text primary key,
              role text,
              team_size integer,
              current_tool text,
              goals text not null default '[]',
              pain_points text not null default '[]',
              features_interested_in text not null default '[]'
            );

            create table if not exists signals(
              id text primary key,
              session_id text not null,
              turn_id integer not null,
              type text not null,
              value text not null,
              confidence real not null,
              created_at text not null
            );

            create table if not exists ui_events(
              id text primary key,
              session_id text not null,
              turn_id integer not null,
              action_type text not null,
              status text not null,
              created_at text not null
            );

            create table if not exists demo_workspace_scopes(
              id text primary key,
              name text not null,
              description text not null,
              allowed_project_ids text not null,
              allowed_issue_projects text not null
            );

            create table if not exists demo_projects(
              id text primary key,
              name text not null,
              description text not null,
              progress integer not null,
              status text not null,
              lead text not null,
              team text not null,
              target_date text not null
            );

            create table if not exists demo_team_members(
              name text primary key,
              initials text not null,
              role text not null,
              load integer not null,
              email text,
              project_ids text not null
            );

            create table if not exists demo_cycles(
              id text primary key,
              name text not null,
              project_id text references demo_projects(id),
              days_left integer not null,
              progress integer not null,
              completed integer not null,
              in_progress integer not null,
              remaining integer not null,
              focus text not null,
              status text not null,
              team text not null,
              start_date text not null,
              end_date text not null
            );

            create table if not exists demo_issues(
              id text primary key,
              title text not null,
              priority text not null,
              assignee text not null,
              project text not null,
              project_id text references demo_projects(id),
              status text not null,
              cycle text,
              estimate text,
              label text,
              description text
            );
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("pragma table_info(sessions)").fetchall()
        }
        if "latest_turn_id" not in columns:
            connection.execute("alter table sessions add column latest_turn_id integer")

    _add_project_foreign_keys()

    # Seed demo auth users after schema is ready.
    from app.auth import seed_demo_users
    seed_demo_users()


# Table definitions used to rebuild databases created before project links existed.
# SQLite cannot add a foreign key to an existing table, so the table is recreated.
_LINKED_TABLES: dict[str, str] = {
    "demo_issues": """
        create table demo_issues_migrated(
          id text primary key,
          title text not null,
          priority text not null,
          assignee text not null,
          project text not null,
          project_id text references demo_projects(id),
          status text not null,
          cycle text,
          estimate text,
          label text,
          description text
        )
    """,
    "demo_cycles": """
        create table demo_cycles_migrated(
          id text primary key,
          name text not null,
          project_id text references demo_projects(id),
          days_left integer not null,
          progress integer not null,
          completed integer not null,
          in_progress integer not null,
          remaining integer not null,
          focus text not null,
          status text not null,
          team text not null,
          start_date text not null,
          end_date text not null
        )
    """,
}


def backup_database() -> Path | None:
    """Copy the database (including any WAL contents) next to it, before migrating."""
    if not DB_PATH.exists():
        return None

    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{DB_PATH.stem}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"

    source = sqlite3.connect(DB_PATH)
    destination = sqlite3.connect(backup_path)
    try:
        with destination:
            source.backup(destination)
    finally:
        source.close()
        destination.close()
    return backup_path


def _add_project_foreign_keys() -> None:
    """Enforce issue and cycle links to projects, rebuilding older databases once."""
    with get_connection() as connection:
        pending = [
            table for table in _LINKED_TABLES
            if not connection.execute(f"pragma foreign_key_list({table})").fetchall()
        ]
    if not pending:
        return

    backup_database()
    for table in pending:
        _rebuild_with_project_link(table)


def _rebuild_with_project_link(table: str) -> None:
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        # Foreign keys must be off, and outside a transaction, to swap tables safely.
        connection.execute("pragma foreign_keys = off")
        connection.execute("begin immediate")
        before = connection.execute(f"select count(*) as count from {table}").fetchone()["count"]
        # Demo rows may point at projects that were never created; keep the row, drop the link.
        connection.execute(
            f"update {table} set project_id = null "
            "where project_id is not null and project_id not in (select id from demo_projects)"
        )
        connection.execute(_LINKED_TABLES[table])
        connection.execute(f"insert into {table}_migrated select * from {table}")
        connection.execute(f"drop table {table}")
        connection.execute(f"alter table {table}_migrated rename to {table}")

        after = connection.execute(f"select count(*) as count from {table}").fetchone()["count"]
        violations = connection.execute("pragma foreign_key_check").fetchall()
        if after != before or violations:
            raise RuntimeError(
                f"Migration of {table} was rolled back: {before} rows before, {after} after, "
                f"{len(violations)} link violations. The pre-migration backup is in data/backups."
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("pragma foreign_keys = on")
        connection.close()
