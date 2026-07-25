from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def default_database_path() -> Path:
    configured = os.environ.get("UU_RUNTIME_DB")
    if configured:
        return Path(configured).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "until-useful" / "runtime.sqlite3"


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def migrate(self) -> None:
        connection = self.connect()
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
            if version == 0:
                connection.executescript(SCHEMA)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            elif version == 1:
                connection.executescript(MIGRATION_1_TO_2)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            if version <= SCHEMA_VERSION:
                connection.executescript(V2_BACKFILL)
                connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        connection = self.connect()
        try:
            row = connection.execute(sql, parameters).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()

    def require_one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any]:
        row = self.one(sql, parameters)
        if row is None:
            raise RuntimeError("required database row was not found")
        return row

    def all(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
        finally:
            connection.close()

    def event(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        event_type: str,
        state_before: str | None,
        state_after: str | None,
        details: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO events(task_id, run_id, event_type, state_before, state_after, details_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, run_id, event_type, state_before, state_after, json.dumps(details or {}, sort_keys=True), utc_now()),
        )


SCHEMA = """
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    repository_path TEXT NOT NULL,
    canonical_plan_path TEXT NOT NULL,
    risk_profile TEXT NOT NULL,
    state TEXT NOT NULL,
    revision_cycle INTEGER NOT NULL DEFAULT 0,
    challenge_cycle INTEGER NOT NULL DEFAULT 0,
    review_epoch INTEGER NOT NULL DEFAULT 1,
    constructive_context_id TEXT,
    review_frontier_context_id TEXT,
    prior_review_context_id TEXT,
    active_challenger_context_id TEXT,
    pending_codex_purpose TEXT,
    initial_handoff TEXT NOT NULL,
    last_codex_handoff TEXT,
    adapter_name TEXT NOT NULL,
    adapter_config_json TEXT NOT NULL DEFAULT '{}',
    stop_reason TEXT,
    final_title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE contexts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    lineage_label TEXT NOT NULL,
    context_class TEXT NOT NULL,
    adapter TEXT NOT NULL,
    harness TEXT NOT NULL,
    model_label TEXT,
    session_id TEXT,
    parent_context_id TEXT REFERENCES contexts(id),
    created_at TEXT NOT NULL,
    retired_at TEXT,
    retirement_reason TEXT,
    is_fresh INTEGER NOT NULL,
    UNIQUE(task_id, lineage_label),
    UNIQUE(adapter, session_id)
);

CREATE UNIQUE INDEX one_active_task_per_repository ON tasks(repository_path)
WHERE state NOT IN ('WAITING_FOR_HUMAN_REVIEW', 'NEEDS_INPUT', 'FAILED', 'BLOCKED', 'STOPPED');

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    context_id TEXT REFERENCES contexts(id),
    protocol TEXT NOT NULL,
    workflow_purpose TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    raw_output TEXT,
    cleaned_report TEXT,
    normalized_result_json TEXT,
    error_json TEXT,
    repository_before_json TEXT,
    repository_after_json TEXT,
    usage_json TEXT,
    validation_diagnostics_json TEXT,
    repair_of_run_id TEXT REFERENCES runs(id),
    repair_prompt_version INTEGER,
    UNIQUE(task_id, sequence_number)
);

CREATE UNIQUE INDEX one_active_run_globally ON runs((1)) WHERE status = 'RUNNING';

CREATE TABLE findings (
    id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    source_run_id TEXT NOT NULL REFERENCES runs(id),
    priority TEXT NOT NULL,
    title TEXT NOT NULL,
    evidence TEXT,
    failure_scenario TEXT,
    impact TEXT,
    correction TEXT,
    status TEXT NOT NULL,
    adjudication_run_id TEXT REFERENCES runs(id),
    disposition TEXT,
    disposition_evidence TEXT,
    verification_run_id TEXT REFERENCES runs(id),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY(task_id, id)
);

CREATE TABLE approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    gate TEXT NOT NULL,
    decision TEXT NOT NULL,
    actor TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES runs(id),
    event_type TEXT NOT NULL,
    state_before TEXT,
    state_after TEXT,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_run_id TEXT REFERENCES runs(id),
    created_at TEXT NOT NULL
);

CREATE TABLE human_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    source_run_id TEXT REFERENCES runs(id),
    guidance TEXT NOT NULL,
    prior_state TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    resolution_run_id TEXT REFERENCES runs(id),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
"""


MIGRATION_1_TO_2 = """
ALTER TABLE runs ADD COLUMN validation_diagnostics_json TEXT;
ALTER TABLE runs ADD COLUMN repair_of_run_id TEXT REFERENCES runs(id);
ALTER TABLE runs ADD COLUMN repair_prompt_version INTEGER;

CREATE TABLE human_inputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    source_run_id TEXT REFERENCES runs(id),
    guidance TEXT NOT NULL,
    prior_state TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    resolution_run_id TEXT REFERENCES runs(id),
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

DROP INDEX one_active_task_per_repository;
CREATE UNIQUE INDEX one_active_task_per_repository ON tasks(repository_path)
WHERE state NOT IN ('WAITING_FOR_HUMAN_REVIEW', 'NEEDS_INPUT', 'FAILED', 'BLOCKED', 'STOPPED');

UPDATE runs
SET status = 'INVALID_OUTPUT',
    validation_diagnostics_json = error_json,
    repair_prompt_version = CASE WHEN sequence_number > 1 THEN 1 ELSE repair_prompt_version END
WHERE status = 'FAILED'
  AND (json_extract(error_json, '$.type') = 'StructuredOutputError'
       OR json_extract(error_json, '$.message') LIKE 'invalid finding %'
       OR json_extract(error_json, '$.message') LIKE '%dispositions are only allowed%'
       OR json_extract(error_json, '$.message') LIKE '%requires only P3 findings%');

UPDATE runs
SET validation_diagnostics_json = COALESCE(validation_diagnostics_json, error_json)
WHERE status = 'INVALID_OUTPUT';

UPDATE tasks
SET state = 'NEEDS_INPUT', updated_at = CURRENT_TIMESTAMP
WHERE state = 'BLOCKED'
  AND EXISTS (SELECT 1 FROM runs WHERE runs.task_id = tasks.id AND runs.status = 'INVALID_OUTPUT');
"""


V2_BACKFILL = """
UPDATE runs AS repair
SET repair_of_run_id = (
    SELECT json_extract(event.details_json, '$.failed_run_id')
    FROM events AS event
    WHERE event.task_id = repair.task_id
      AND event.event_type = 'INVALID_OUTPUT_RECOVERY_STARTED'
      AND json_extract(event.details_json, '$.failed_run_id') IS NOT NULL
    ORDER BY event.id DESC LIMIT 1
)
WHERE repair.repair_of_run_id IS NULL
  AND repair.repair_prompt_version = 1
  AND EXISTS (
    SELECT 1 FROM events AS event
    WHERE event.task_id = repair.task_id
      AND event.event_type = 'INVALID_OUTPUT_RECOVERY_STARTED'
      AND json_extract(event.details_json, '$.failed_run_id') IS NOT NULL
  );
"""
