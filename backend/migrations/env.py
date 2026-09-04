"""Alembic environment for the Wave 0 baseline."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from app.core.db import _sqlite_pragmas
from app.core.models import Base
from app.modules.debates import models as _debate_models
from app.modules.interactions import models as _interaction_models
from app.modules.reports import models as _report_models
from sqlalchemy import engine_from_config, event, pool

del _debate_models, _interaction_models, _report_models

config = context.config
if config.config_file_name is not None:
    # Migrations run inside the application process at startup, after the
    # application has installed its stdout log handler. The default
    # ``disable_existing_loggers=True`` would silently disable that handler,
    # so every later application log — including the only record of why a
    # provider turn failed — would be dropped inside the container.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    configured = config.attributes.get("database_url")
    if isinstance(configured, str):
        return configured
    resolved = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    if not resolved:
        raise RuntimeError("DATABASE_URL is required for migrations")
    return resolved


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    # Register before the first connection is checked out.  In particular,
    # journal_mode=WAL must be applied at connection-open time; issuing it
    # after Alembic starts its migration transaction can make SQLite discard
    # the version-row write while retaining DDL.
    if connectable.dialect.name == "sqlite":
        event.listen(connectable, "connect", _sqlite_pragmas)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
