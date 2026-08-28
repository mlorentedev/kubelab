"""PostgreSQL tenant provisioner: idempotent role, database, and permission setup."""

from __future__ import annotations

import re


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
