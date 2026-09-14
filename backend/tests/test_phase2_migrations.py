from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from database import Base
import models  # noqa: F401
from app.persistence.models import PHASE2_TABLE_NAMES  # noqa: F401


BACKEND_DIR = Path(__file__).resolve().parents[1]
def test_phase2_migration_upgrade_and_rollback(monkeypatch):
    database_path = BACKEND_DIR / ".phase2-migration-test.db"
    database_path.unlink(missing_ok=True)
    url = f"sqlite:///{database_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    upgraded_tables = set(inspect(engine).get_table_names())
    assert set(PHASE2_TABLE_NAMES) <= upgraded_tables
    assert {"cases", "wallets", "transactions"} <= upgraded_tables
    engine.dispose()

    command.downgrade(config, "20260912_0000")
    engine = create_engine(url)
    rolled_back_tables = set(inspect(engine).get_table_names())
    assert set(PHASE2_TABLE_NAMES).isdisjoint(rolled_back_tables)
    assert {"cases", "wallets", "transactions"} <= rolled_back_tables
    engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(url)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
    database_path.unlink(missing_ok=True)


def test_existing_legacy_database_can_be_stamped_and_upgraded(monkeypatch):
    database_path = BACKEND_DIR / ".phase2-existing-test.db"
    database_path.unlink(missing_ok=True)
    url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(url)
    legacy_tables = [
        table for name, table in Base.metadata.tables.items()
        if name not in PHASE2_TABLE_NAMES
    ]
    Base.metadata.create_all(engine, tables=legacy_tables)
    engine.dispose()

    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.stamp(config, "20260912_0000")
    command.upgrade(config, "head")

    engine = create_engine(url)
    assert set(PHASE2_TABLE_NAMES) <= set(inspect(engine).get_table_names())
    engine.dispose()
    database_path.unlink(missing_ok=True)


def test_postgresql_schema_uses_timezone_aware_columns():
    ddl = str(CreateTable(Base.metadata.tables["normalized_transactions"]).compile(dialect=postgresql.dialect()))
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "event_time" in ddl and "available_time" in ddl and "ingested_at" in ddl
