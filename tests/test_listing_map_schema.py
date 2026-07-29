class _RecordingConnection:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self


def test_listing_map_location_migration_is_idempotent_and_non_destructive():
    from db.schema import _migrate_listing_map_locations

    conn = _RecordingConnection()

    _migrate_listing_map_locations(conn)
    _migrate_listing_map_locations(conn)

    ddl = "\n".join(sql for sql, _params in conn.executed)
    required_fragments = [
        "listing_id BIGINT PRIMARY KEY REFERENCES listings(id) ON DELETE CASCADE",
        "lat DOUBLE PRECISION NOT NULL CHECK (lat BETWEEN -90 AND 90)",
        "lng DOUBLE PRECISION NOT NULL CHECK (lng BETWEEN -180 AND 180)",
        "location_precision TEXT NOT NULL",
        "location_key TEXT NOT NULL",
        "resolver_version TEXT NOT NULL",
        "listing_location_signature TEXT NOT NULL",
        "idx_listing_map_locations_precision",
        "idx_listing_map_locations_point",
        "idx_listing_map_locations_key",
    ]
    for fragment in required_fragments:
        assert fragment in ddl

    upper = ddl.upper()
    assert "DROP TABLE" not in upper
    assert "TRUNCATE " not in upper
    assert "UPDATE LISTINGS" not in upper
    assert ddl.count("CREATE TABLE IF NOT EXISTS listing_map_locations") == 2


def test_listing_map_location_migration_supports_all_honest_precisions():
    from db.schema import _migrate_listing_map_locations

    conn = _RecordingConnection()
    _migrate_listing_map_locations(conn)
    ddl = "\n".join(sql for sql, _params in conn.executed)

    for column in (
        "accuracy_radius_m DOUBLE PRECISION",
        "relation TEXT",
        "reference_road TEXT",
        "landmark_key TEXT",
        "resolution_status TEXT",
        "resolution_reason TEXT",
    ):
        assert column in ddl
    assert "'landmark'" in ddl
    assert "'nearby'" in ddl
    assert "CREATE TABLE IF NOT EXISTS listing_map_location_coverage" in ddl
    assert "DROP TABLE" not in ddl.upper()
    assert "TRUNCATE" not in ddl.upper()
    assert "UPDATE LISTINGS" not in ddl.upper()


def test_full_schema_contains_derived_location_table():
    from db.schema import SCHEMA_SQL

    assert "CREATE TABLE IF NOT EXISTS listing_map_locations" in SCHEMA_SQL
    assert (
        "CHECK (location_precision IN "
        "('exact', 'road', 'landmark', 'nearby', 'ward'))"
    ) in SCHEMA_SQL
    assert "CREATE TABLE IF NOT EXISTS listing_map_location_coverage" in SCHEMA_SQL
