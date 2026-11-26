import json
import errno
import os
from types import SimpleNamespace

import pytest

import cli.data_import as data_import
from db.connection import PgConnection, PgCursor


class _ExportCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        return self

    def __iter__(self):
        return iter(self.rows)


class _ExportConnection:
    def __init__(self, cursor):
        self.export_cursor = cursor
        self.cursor_name = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self, *, name=None):
        self.cursor_name = name
        return self.export_cursor


def _raw_rows():
    return [
        {
            "source": "facebook",
            "source_id": "post-1",
            "url": "https://example.test/1",
            "raw_json": json.dumps({"title": "Listing 1", "nested": [1, 2], "line_separator": "before\u2028middle\u2029after"}),
            "crawled_at": "2026-10-17T10:00:00+07:00",
        },
        {
            "source": "guland",
            "source_id": "post-2",
            "url": "https://example.test/2",
            "raw_json": json.dumps({"title": "Listing 2"}),
            "crawled_at": "2026-10-17T10:01:00+07:00",
        },
    ]


def test_pg_connection_forwards_named_cursor_to_psycopg():
    class _RawConnection:
        def __init__(self):
            self.cursor_kwargs = None

        def cursor(self, **kwargs):
            self.cursor_kwargs = kwargs
            return object()

    raw = _RawConnection()
    cursor = PgConnection(raw).cursor(name="raw_backup_export")

    assert isinstance(cursor, PgCursor)
    assert raw.cursor_kwargs == {"name": "raw_backup_export"}


def test_cmd_export_raw_streams_rows_through_named_cursor(tmp_path, monkeypatch, capsys):
    rows = _raw_rows()
    cursor = _ExportCursor(rows)
    connection = _ExportConnection(cursor)
    output = tmp_path / "raw_backup.json"
    output.write_text("old backup", encoding="utf-8")

    monkeypatch.setattr(data_import, "init_schema", lambda: None)
    monkeypatch.setattr(data_import, "get_conn", lambda: connection)

    data_import.cmd_export_raw(SimpleNamespace(out=str(output)))

    expected = [
        {
            "source": row["source"],
            "source_id": row["source_id"],
            "url": row["url"],
            "raw_json": json.loads(row["raw_json"]),
            "crawled_at": row["crawled_at"],
        }
        for row in rows
    ]
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert connection.cursor_name == "raw_backup_export"
    assert "SELECT source, source_id, url, raw_json, crawled_at FROM raw_listings ORDER BY id" in cursor.sql
    assert "Exported 2 raw records" in capsys.readouterr().out
    assert output.stat().st_size < len(json.dumps(expected, ensure_ascii=False, indent=2).encode())


def test_cmd_export_raw_preserves_symlink_destination(tmp_path, monkeypatch):
    rows = _raw_rows()
    connection = _ExportConnection(_ExportCursor(rows))
    target = tmp_path / "actual-backup.json"
    target.write_text("old backup", encoding="utf-8")
    output = tmp_path / "raw_backup.json"
    output.symlink_to(target)
    monkeypatch.setattr(data_import, "init_schema", lambda: None)
    monkeypatch.setattr(data_import, "get_conn", lambda: connection)

    data_import.cmd_export_raw(SimpleNamespace(out=str(output)))

    assert output.is_symlink()
    assert len(json.loads(target.read_text(encoding="utf-8"))) == len(rows)


def test_cmd_export_raw_keeps_previous_backup_if_stream_fails(tmp_path, monkeypatch):
    rows = _raw_rows()

    class _FailingCursor(_ExportCursor):
        def __iter__(self):
            yield self.rows[0]
            raise RuntimeError("stream interrupted")

    connection = _ExportConnection(_FailingCursor(rows))
    output = tmp_path / "raw_backup.json"
    output.write_text("previous complete backup", encoding="utf-8")
    monkeypatch.setattr(data_import, "init_schema", lambda: None)
    monkeypatch.setattr(data_import, "get_conn", lambda: connection)

    with pytest.raises(RuntimeError, match="stream interrupted"):
        data_import.cmd_export_raw(SimpleNamespace(out=str(output)))

    assert output.read_text(encoding="utf-8") == "previous complete backup"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_full_disk_preserves_previous_backup_and_cleans_temp(tmp_path, monkeypatch):
    output = tmp_path / "raw_backup.json"
    output.write_text("previous complete backup", encoding="utf-8")
    monkeypatch.setattr(data_import, "init_schema", lambda: None)
    monkeypatch.setattr(data_import, "get_conn", lambda: _ExportConnection(_ExportCursor(_raw_rows())))
    def disk_full(_fd):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(data_import.os, "fsync", disk_full)
    with pytest.raises(OSError) as exc:
        data_import.cmd_export_raw(SimpleNamespace(out=str(output)))
    assert exc.value.errno == errno.ENOSPC
    assert output.read_text(encoding="utf-8") == "previous complete backup"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_daily_backup_marks_disk_full_partial_and_propagates_other_errors(monkeypatch):
    from cli import crawlers
    from unittest.mock import Mock
    mark = Mock()
    monkeypatch.setattr(crawlers, "mark_partial", mark)
    export = Mock(side_effect=OSError(errno.ENOSPC, "disk full"))
    monkeypatch.setattr(crawlers, "cmd_export_raw", export)
    crawlers._export_crawl_backup(SimpleNamespace(out=None))
    mark.assert_called_once()
    export.side_effect = OSError(errno.EACCES, "permission denied")
    with pytest.raises(OSError):
        crawlers._export_crawl_backup(SimpleNamespace(out=None))
