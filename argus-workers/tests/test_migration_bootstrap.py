"""Tests for the base-schema bootstrap in database.migrations.runner.

A fresh database used to fail at migration 003 (`organizations` missing)
unless someone had applied `database/init/*.sql` by hand — Docker only did
that through `docker-entrypoint-initdb.d`. These tests pin the runner's own
bootstrap, without needing a live PostgreSQL.
"""

import pytest

from database.migrations.runner import _bootstrap_base_schema


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql):
        self.connection.executed.append(sql)
        if self.connection.fail_on and self.connection.fail_on in sql:
            raise RuntimeError("simulated migration failure")

    def fetchone(self):
        return (self.connection.organizations,)


class FakeConnection:
    def __init__(self, organizations, fail_on=None):
        self.organizations = "organizations" if organizations else None
        self.fail_on = fail_on
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_applies_init_files_when_base_schema_is_absent():
    conn = FakeConnection(organizations=False)

    applied = _bootstrap_base_schema(conn)

    assert applied == ["01-schema.sql", "02-audit.sql"]
    assert conn.executed[0] == "SELECT to_regclass('public.organizations')"
    assert "CREATE TABLE IF NOT EXISTS engagements" in conn.executed[1]
    assert "CREATE TABLE IF NOT EXISTS audit_log" in conn.executed[2]
    assert conn.commits == 1
    assert conn.rollbacks == 0


def test_skips_bootstrap_when_base_schema_already_exists():
    conn = FakeConnection(organizations=True)

    applied = _bootstrap_base_schema(conn)

    assert applied == []
    assert conn.executed == ["SELECT to_regclass('public.organizations')"]
    assert conn.commits == 0


def test_partial_failure_rolls_back_and_raises():
    conn = FakeConnection(organizations=False, fail_on="CREATE EXTENSION")

    with pytest.raises(RuntimeError, match="simulated migration failure"):
        _bootstrap_base_schema(conn)

    assert conn.rollbacks == 1
    assert conn.commits == 0
    # The second init file never ran: a failed bootstrap is not half-applied.
    assert len(conn.executed) == 2
