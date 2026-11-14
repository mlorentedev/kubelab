"""PostgreSQL tenant provisioner: idempotent role, database, and permission setup."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Where each tenant's role password lives in SOPS. A tenant names both its role and its database.
TENANT_PASSWORD_PATHS: dict[str, str] = {
    "vikunja": "apps.services.core.vikunja.db_password",
    "api": "apps.platform.api.db_password",
}


@dataclass(frozen=True)
class ReaderRole:
    """A login that reads named views of a tenant's database and nothing else (CONSOLE-004 AC6)."""

    password_path: str
    database: str
    views: tuple[str, ...]


# Read-only roles. Unlike a tenant, a reader owns no database: it is bound to one a tenant
# already has, and holds SELECT on the listed views only. `forge_stats` is Grafana's login
# on the forge read model's counts-only view (`apps/api/migrations/*_forge_stats.sql`).
READER_ROLES: dict[str, ReaderRole] = {
    "forge_stats": ReaderRole(
        password_path="apps.platform.api.forge_stats_db_password",
        database="api",
        views=("forge_stats",),
    ),
}

# Every role the provisioner manages, by name: the CLI's `--tenant` accepts any of them.
ROLE_PASSWORD_PATHS: dict[str, str] = {
    **TENANT_PASSWORD_PATHS,
    **{name: reader.password_path for name, reader in READER_ROLES.items()},
}


def _escape_sql_literal(value: str) -> str:
    """Escape single quotes for inclusion in a SQL string literal."""
    return value.replace("'", "''")


def build_provision_sql(username: str, password: str, database: str) -> str:
    """Generate an idempotent SQL script to provision a tenant role and database."""
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        raise ValueError(f"Invalid username: {username}")
    if not re.match(r"^[a-zA-Z0-9_]+$", database):
        raise ValueError(f"Invalid database name: {database}")

    escaped_password = _escape_sql_literal(password)

    return f"""DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{username}') THEN
    CREATE ROLE {username} WITH LOGIN PASSWORD '{escaped_password}';
  ELSE
    ALTER ROLE {username} WITH PASSWORD '{escaped_password}';
  END IF;
END
$$;

SELECT 'CREATE DATABASE {database} OWNER {username}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{database}')\\gexec

REVOKE ALL ON DATABASE {database} FROM PUBLIC;
GRANT ALL PRIVILEGES ON DATABASE {database} TO {username};
REVOKE CONNECT ON DATABASE kubelab FROM {username};
"""


def build_reader_sql(username: str, password: str, database: str, views: tuple[str, ...]) -> str:
    """Generate an idempotent SQL script for a read-only role on views of an existing database.

    The grant is guarded by `to_regclass`, so the script is safe to run before the migration
    that creates the view; the migration grants the same SELECT when the role already exists,
    so either order ends with it in place. The script stops at its first failed statement:
    psql would otherwise exit 0 and a grant that did not land would read as provisioned.
    """
    for name in (username, database, *views):
        if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
            raise ValueError(f"Invalid identifier: {name!r}")

    escaped_password = _escape_sql_literal(password)
    attributes = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT"
    grants = "\n".join(
        f"""DO $$
BEGIN
  IF to_regclass('public.{view}') IS NOT NULL THEN
    GRANT SELECT ON public.{view} TO {username};
  END IF;
END
$$;"""
        for view in views
    )

    return f"""\\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{username}') THEN
    CREATE ROLE {username} WITH {attributes} PASSWORD '{escaped_password}';
  ELSE
    ALTER ROLE {username} WITH {attributes} PASSWORD '{escaped_password}';
  END IF;
END
$$;

ALTER ROLE {username} SET default_transaction_read_only = on;
ALTER ROLE {username} SET statement_timeout = '15s';

GRANT CONNECT ON DATABASE {database} TO {username};

\\connect {database}
GRANT USAGE ON SCHEMA public TO {username};
{grants}
"""
