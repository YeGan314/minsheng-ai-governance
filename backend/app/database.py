from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, Text, create_engine, event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.settings import settings

os.umask(0o077)

metadata = MetaData()

config_drafts = Table(
    "config_drafts", metadata,
    Column("id", String(36), primary_key=True),
    Column("title", String(120), nullable=False),
    Column("status", String(20), nullable=False, server_default="draft"),
    Column("config", JSON, nullable=False),
    Column("messages", JSON, nullable=False, server_default=text("'[]'")),
    Column("validation", JSON),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
config_versions = Table(
    "config_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("version", String(32), nullable=False, unique=True),
    Column("draft_id", String(36), nullable=False),
    Column("title", String(120), nullable=False),
    Column("config", JSON, nullable=False),
    Column("publisher", String(100), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
sample_runs = Table(
    "sample_runs", metadata,
    Column("id", String(36), primary_key=True),
    Column("draft_id", String(36), nullable=False),
    Column("source_dataset", String(200), nullable=False),
    Column("sample_count", Integer, nullable=False),
    Column("result", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
data_sources = Table(
    "data_sources", metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("kind", String(24), nullable=False),
    Column("provider", String(40), nullable=False),
    Column("config", JSON, nullable=False),
    Column("encrypted_secrets", Text, nullable=False, server_default=""),
    Column("is_default", Integer, nullable=False, server_default="0"),
    Column("enabled", Integer, nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

governance_configs = Table(
    "governance_configs", metadata,
    Column("section", String(64), primary_key=True),
    Column("revision", Integer, nullable=False, server_default="1"),
    Column("config", JSON, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
governance_config_revisions = Table(
    "governance_config_revisions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("section", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("config", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
governance_profiles = Table(
    "governance_profiles", metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("settings", JSON, nullable=False, server_default=text("'{}'")),
    Column("status", String(20), nullable=False, server_default="draft"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
governance_profile_versions = Table(
    "governance_profile_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("profile_id", String(36), nullable=False),
    Column("version", String(32), nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("publisher", String(100), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the application's local, persistent SQLite engine."""
    path = Path(settings.SQLITE_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_size=5,
        max_overflow=5,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
        for file_path in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            try:
                file_path.chmod(0o600)
            except OSError:
                pass

    return engine


@lru_cache(maxsize=1)
def get_source_engine() -> Engine | None:
    """Optional read-only source connector; application state never depends on it."""
    if not settings.DATABASE_URL:
        return None
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2)


def _migrate_legacy_postgres(engine: Engine) -> None:
    """Copy existing governance state from the former PostgreSQL store once, without deleting it."""
    legacy_url = settings.LEGACY_GOVERNANCE_DATABASE_URL or settings.DATABASE_URL
    if not legacy_url or not legacy_url.startswith(("postgresql", "postgres")):
        return
    legacy_engine = create_engine(legacy_url, pool_pre_ping=True)
    tables = {"config_drafts": config_drafts, "config_versions": config_versions, "sample_runs": sample_runs}
    try:
        inspector = __import__("sqlalchemy").inspect(legacy_engine)
        with legacy_engine.connect() as old, engine.begin() as new:
            for name, table in tables.items():
                if not inspector.has_table(name, schema="governance"):
                    continue
                rows = old.exec_driver_sql(f'SELECT * FROM "governance"."{name}"').mappings().all()
                for row in rows:
                    values = dict(row)
                    if name == "config_drafts":
                        values["config"] = values.get("config") or {}
                        values["messages"] = values.get("messages") or []
                    if name in {"config_versions", "sample_runs"}:
                        values["config" if name == "config_versions" else "result"] = values.get("config" if name == "config_versions" else "result") or {}
                    exists = new.execute(table.select().where(table.c["id" if name != "config_versions" else "version"] == values["id" if name != "config_versions" else "version"])).first()
                    if not exists:
                        new.execute(table.insert().values(**values))
    except SQLAlchemyError:
        # Migration is best effort; local SQLite remains usable if old source tables are unavailable.
        return
    finally:
        legacy_engine.dispose()


def initialize_database() -> None:
    engine = get_engine()
    with engine.begin() as connection:
        metadata.create_all(connection)
        # SQLite CREATE TABLE IF NOT EXISTS does not add columns to a table
        # created by an earlier development build; keep this small migration
        # local and idempotent for existing governance profile databases.
        if inspect(connection).has_table("governance_profiles"):
            columns = {column["name"] for column in inspect(connection).get_columns("governance_profiles")}
            if "settings" not in columns:
                connection.exec_driver_sql("ALTER TABLE governance_profiles ADD COLUMN settings JSON NOT NULL DEFAULT '{}' ")
        # Preserve the current value as the first immutable rule revision when
        # upgrading a database that already has module-level configurations.
        existing_configs = connection.execute(select(governance_configs)).mappings().all()
        for row in existing_configs:
            revision_exists = connection.execute(
                select(governance_config_revisions.c.id).where(
                    governance_config_revisions.c.section == row["section"],
                    governance_config_revisions.c.revision == row["revision"],
                )
            ).first()
            if not revision_exists:
                connection.execute(governance_config_revisions.insert().values(
                    section=row["section"], revision=row["revision"], config=row["config"], created_at=row["updated_at"]
                ))
    if settings.MIGRATE_LEGACY_GOVERNANCE:
        _migrate_legacy_postgres(engine)
