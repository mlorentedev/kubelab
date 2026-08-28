"""Unit tests for PostgreSQL tenant database provisioner."""

from __future__ import annotations

from toolkit.features.postgres_provisioner import build_provision_sql


def test_build_provision_sql_contains_idempotent_role_and_db_creation():
    sql = build_provision_sql(username="vikunja", password="secret_password_123", database="vikunja")

    assert "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vikunja')" in sql
    assert "CREATE ROLE vikunja WITH LOGIN PASSWORD 'secret_password_123'" in sql
    assert "SELECT 'CREATE DATABASE vikunja OWNER vikunja'" in sql
    assert "GRANT ALL PRIVILEGES ON DATABASE vikunja TO vikunja" in sql
    assert "REVOKE ALL ON DATABASE vikunja FROM PUBLIC" in sql


def test_build_provision_sql_escapes_single_quotes_in_password():
    sql = build_provision_sql(username="vikunja", password="secret'password", database="vikunja")
    assert "secret''password" in sql
