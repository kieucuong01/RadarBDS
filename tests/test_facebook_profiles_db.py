from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path


class RecordingConnection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        rows = self.rows.pop(0) if self.rows else []
        return RecordingCursor(rows)


class RecordingCursor:
    def __init__(self, rows):
        self.rows = rows if isinstance(rows, list) else [rows]
        self.rowcount = len(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


@contextmanager
def connection_factory(connection):
    yield connection


def sample_profiles():
    return [
        {
            "city": "Thu Dau Mot",
            "url": "https://m.facebook.com/broker-a/?ref=bookmarks",
            "broker_name": "Broker A",
            "daily_limit": 30,
            "range_days": 9,
            "crawl_every_days": 3,
            "active": True,
        },
        {
            "city": "Ben Cat",
            "url": "https://www.facebook.com/broker-b",
            "broker_name": "Broker B",
            "daily_limit": 20,
            "range_days": 14,
            "crawl_every_days": 7,
            "active": False,
        },
    ]


def test_facebook_profile_migration_is_idempotent_and_db_native():
    from db.schema import _migrate_facebook_crawl_profiles

    connection = RecordingConnection()
    _migrate_facebook_crawl_profiles(connection)
    _migrate_facebook_crawl_profiles(connection)

    ddl = "\n".join(sql for sql, _params in connection.executed)
    compact = " ".join(ddl.split())
    assert ddl.count("CREATE TABLE IF NOT EXISTS facebook_crawl_profiles") == 2
    assert "url TEXT PRIMARY KEY" in compact
    assert "daily_limit INTEGER NOT NULL DEFAULT 20" in compact
    assert "crawl_every_days INTEGER NOT NULL DEFAULT 1" in compact
    assert "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_facebook_crawl_profiles_active" in ddl
    assert "data/facebook_profiles.json" not in ddl
    assert "DROP TABLE" not in ddl.upper()


def test_profile_repository_writes_normalized_profiles_to_db_not_json(tmp_path):
    from db.facebook_profiles import write_profile_config

    legacy_path = tmp_path / "facebook_profiles.json"
    legacy_path.write_text('{"old": []}', encoding="utf-8")
    before = legacy_path.read_text(encoding="utf-8")
    connection = RecordingConnection()

    saved = write_profile_config(
        sample_profiles(),
        conn_factory=lambda: connection_factory(connection),
        updated_by="admin@example.test",
    )

    assert [item["url"] for item in saved] == [
        "https://www.facebook.com/broker-a",
        "https://www.facebook.com/broker-b",
    ]
    assert saved[0]["daily_limit"] == 30
    assert saved[0]["tier"] == 30
    assert saved[1]["active"] is False
    assert legacy_path.read_text(encoding="utf-8") == before
    sql = "\n".join(statement for statement, _params in connection.executed)
    assert "DELETE FROM facebook_crawl_profiles" in sql
    assert "INSERT INTO facebook_crawl_profiles" in sql
    insert_params = [
        params
        for statement, params in connection.executed
        if "INSERT INTO facebook_crawl_profiles" in statement
    ]
    assert insert_params[0][0] == "https://www.facebook.com/broker-a"
    assert insert_params[0][-1] == "admin@example.test"


def test_profile_repository_reads_db_rows_in_existing_api_shape():
    from db.facebook_profiles import read_profile_config

    rows = [[
        {
            "city": "Thu Dau Mot",
            "url": "https://www.facebook.com/broker-a",
            "broker_name": "Broker A",
            "daily_limit": 30,
            "range_days": 9,
            "crawl_every_days": 3,
            "active": True,
        },
        {
            "city": "Ben Cat",
            "url": "https://www.facebook.com/broker-b",
            "broker_name": "Broker B",
            "daily_limit": 20,
            "range_days": 14,
            "crawl_every_days": 7,
            "active": False,
        },
    ]]
    connection = RecordingConnection(rows=rows)

    profiles = read_profile_config(
        conn_factory=lambda: connection_factory(connection),
    )

    assert profiles == [
        {
            "city": "Thu Dau Mot",
            "url": "https://www.facebook.com/broker-a",
            "broker_name": "Broker A",
            "tier": 30,
            "daily_limit": 30,
            "range_days": 9,
            "crawl_every_days": 3,
            "active": True,
        },
        {
            "city": "Ben Cat",
            "url": "https://www.facebook.com/broker-b",
            "broker_name": "Broker B",
            "tier": 20,
            "daily_limit": 20,
            "range_days": 14,
            "crawl_every_days": 7,
            "active": False,
        },
    ]
    sql = connection.executed[0][0]
    assert "FROM facebook_crawl_profiles" in sql
    assert "ORDER BY active DESC, city, broker_name, url" in sql


def test_crawler_load_profiles_requires_db_and_never_falls_back_to_json(monkeypatch, tmp_path):
    from crawler import facebook_apify

    legacy_path = tmp_path / "facebook_profiles.json"
    legacy_path.write_text(
        json.dumps({"Legacy": [{"url": "https://www.facebook.com/from-file"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        facebook_apify.db_facebook_profiles,
        "read_profile_config",
        lambda **_kwargs: sample_profiles(),
    )
    loaded = facebook_apify.load_profiles()

    assert [item["url"] for item in loaded] == [
        "https://www.facebook.com/broker-a",
    ]
    assert loaded[0]["broker_name"] == "Broker A"
    assert loaded[0]["default_area"] == "Thu Dau Mot"
    assert loaded[0]["tier"] == 30

    def fail_db(**_kwargs):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(facebook_apify.db_facebook_profiles, "read_profile_config", fail_db)
    try:
        facebook_apify.load_profiles()
    except RuntimeError as exc:
        assert "db unavailable" in str(exc)
    else:
        raise AssertionError("load_profiles must not fall back to JSON")


def test_deploy_scripts_stop_preserving_or_importing_legacy_profile_json():
    deploy = Path("scripts/deploy_production.ps1").read_text(encoding="utf-8")
    ship = Path("scripts/ship_production.ps1").read_text(encoding="utf-8")

    for source in (deploy, ship):
        assert "data/facebook_profiles.json|data/raw_backup.json" not in source
        assert "migrate_facebook_profiles_to_db.py" not in source
        assert "preserve production facebook profiles" not in source
        assert "legacy Facebook profile JSON removed before DB-only deploy" in source
