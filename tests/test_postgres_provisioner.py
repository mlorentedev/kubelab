"""Unit tests for PostgreSQL tenant database provisioner."""

from __future__ import annotations

import pytest

from toolkit.features.postgres_provisioner import (
    READER_ROLES,
    TENANT_PASSWORD_PATHS,
    build_provision_sql,
    build_reader_sql,
)


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


# CONSOLE-004 AC6: Grafana's read-only role on the forge statistics view.

# A placeholder, not a credential: the tests read the script, and no database sees it.
PLACEHOLDER = "placeholder-not-a-secret"
FORGE_STATS_SQL = build_reader_sql(username="forge_stats", password=PLACEHOLDER, database="api", views=("forge_stats",))


def _grants(sql: str) -> list[str]:
    return [line.strip() for line in sql.splitlines() if line.strip().upper().startswith("GRANT")]


def test_the_reader_is_declared_against_the_apis_database_and_the_stats_view() -> None:
    reader = READER_ROLES["forge_stats"]
    assert reader.database == "api"
    assert reader.views == ("forge_stats",)
    # A reader is never also a tenant: a tenant owns a database named after it.
    assert "forge_stats" not in TENANT_PASSWORD_PATHS


def test_the_reader_can_log_in_and_is_otherwise_unprivileged() -> None:
    assert "CREATE ROLE forge_stats WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" in FORGE_STATS_SQL
    assert "ALTER ROLE forge_stats WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT" in FORGE_STATS_SQL
    assert "ALTER ROLE forge_stats SET default_transaction_read_only = on" in FORGE_STATS_SQL


def test_the_reader_holds_select_on_the_view_and_nothing_else() -> None:
    grants = _grants(FORGE_STATS_SQL)
    selects = [g for g in grants if "SELECT" in g]
    assert selects == ["GRANT SELECT ON public.forge_stats TO forge_stats;"]
    assert "GRANT CONNECT ON DATABASE api TO forge_stats;" in grants
    assert not [g for g in grants if "ALL" in g.upper().split()]
    assert "CREATE DATABASE" not in FORGE_STATS_SQL
    assert "forge_item" not in FORGE_STATS_SQL
    assert "forge_source" not in FORGE_STATS_SQL


def test_the_grant_waits_for_a_view_that_does_not_exist_yet() -> None:
    # The provisioner can run before the migration Job has created the view.
    assert "to_regclass('public.forge_stats') IS NOT NULL" in FORGE_STATS_SQL


def test_a_failed_statement_stops_the_script() -> None:
    # psql exits 0 after a failed statement unless told otherwise, and a grant that did not
    # land would read as provisioned.
    assert FORGE_STATS_SQL.startswith("\\set ON_ERROR_STOP on")
    assert FORGE_STATS_SQL.index("\\connect api") > FORGE_STATS_SQL.index("CREATE ROLE")


def test_the_reader_escapes_the_password() -> None:
    sql = build_reader_sql(username="forge_stats", password="a'b", database="api", views=("forge_stats",))
    assert "a''b" in sql


def test_the_reader_refuses_an_unsafe_identifier() -> None:
    for bad in ("x; DROP ROLE y", "a b", ""):
        with pytest.raises(ValueError):
            build_reader_sql(username=bad, password="p", database="api", views=("forge_stats",))
        with pytest.raises(ValueError):
            build_reader_sql(username="forge_stats", password="p", database=bad, views=("forge_stats",))
        with pytest.raises(ValueError):
            build_reader_sql(username="forge_stats", password="p", database="api", views=(bad,))
