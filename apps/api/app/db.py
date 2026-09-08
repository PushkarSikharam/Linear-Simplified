from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
API_DIR = APP_DIR.parent
DATA_DIR = API_DIR / "data"
DB_PATH = DATA_DIR / "demo_agent.sqlite3"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
              project_id text,
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
              project_id text,
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
