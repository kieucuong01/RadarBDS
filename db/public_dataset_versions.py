"""Durable monotonic versions for public read datasets."""

from collections.abc import Iterable


DATASET_SIGNALS = "signals"
DATASET_LISTINGS = "listings"
DATASET_MARKET = "market"
ALLOWED_DATASETS = frozenset(
    {DATASET_SIGNALS, DATASET_LISTINGS, DATASET_MARKET}
)


def _validated(names: Iterable[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(name) for name in names))
    if not result or any(name not in ALLOWED_DATASETS for name in result):
        raise ValueError("invalid public dataset name")
    return result


def get_dataset_versions(conn, names: tuple[str, ...]) -> dict[str, int]:
    validated = _validated(names)
    placeholders = ",".join("?" for _ in validated)
    rows = conn.execute(
        "SELECT dataset_name, version FROM public_dataset_versions "
        f"WHERE dataset_name IN ({placeholders})",
        validated,
    ).fetchall()
    found = {str(row["dataset_name"]): int(row["version"]) for row in rows}
    return {name: found.get(name, 0) for name in validated}


def bump_dataset_versions(conn, names: tuple[str, ...]) -> dict[str, int]:
    validated = _validated(names)
    versions: dict[str, int] = {}
    for name in validated:
        row = conn.execute(
            """
            INSERT INTO public_dataset_versions(dataset_name, version, updated_at)
            VALUES (?, 1, NOW())
            ON CONFLICT (dataset_name) DO UPDATE SET
                version=public_dataset_versions.version + 1,
                updated_at=NOW()
            RETURNING version
            """,
            (name,),
        ).fetchone()
        versions[name] = int(row["version"])
    return versions
