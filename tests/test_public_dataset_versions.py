import pytest

from db import connection
from db.schema import init_schema


@pytest.fixture(autouse=True)
def initialized_schema():
    connection.close_all()
    init_schema()
    yield
    connection.close_all()


def test_public_dataset_version_schema_has_required_rows():
    with connection.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT dataset_name, version
            FROM public_dataset_versions
            ORDER BY dataset_name
            """
        ).fetchall()

    assert [row["dataset_name"] for row in rows] == [
        "listings",
        "market",
        "signals",
    ]
    assert all(int(row["version"]) >= 0 for row in rows)


def test_public_dataset_version_bump_is_monotonic():
    from db.public_dataset_versions import (
        bump_dataset_versions,
        get_dataset_versions,
    )

    with connection.get_conn() as conn:
        before = get_dataset_versions(conn, ("signals",))["signals"]
        bumped = bump_dataset_versions(conn, ("signals",))["signals"]
        after = get_dataset_versions(conn, ("signals",))["signals"]

    assert bumped == before + 1
    assert after == bumped


def test_public_dataset_version_bump_rolls_back_on_error():
    from db.public_dataset_versions import (
        bump_dataset_versions,
        get_dataset_versions,
    )

    with connection.get_conn() as conn:
        before = get_dataset_versions(conn, ("signals",))["signals"]
        try:
            bump_dataset_versions(conn, ("signals",))
            raise RuntimeError("force rollback")
        except RuntimeError:
            conn.rollback()

    with connection.get_conn() as conn:
        assert get_dataset_versions(conn, ("signals",))["signals"] == before


def test_public_dataset_versions_reject_unknown_names():
    from db.public_dataset_versions import get_dataset_versions

    with connection.get_conn() as conn:
        with pytest.raises(ValueError, match="invalid public dataset name"):
            get_dataset_versions(conn, ("secret",))
