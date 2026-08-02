def test_benchmark_reuses_only_warm_connection_and_never_prints_body(
    monkeypatch,
    capsys,
):
    from scripts import benchmark_public_read_path as benchmark

    connections = []

    class _Response:
        status = 200
        reason = "OK"

        def read(self):
            return b"secret-response-body"

    class _Connection:
        def __init__(self):
            self.requests = []
            self.closed = False

        def request(self, method, path, headers=None):
            self.requests.append((method, path, headers))

        def getresponse(self):
            return _Response()

        def close(self):
            self.closed = True

    def fake_connection(_target, _timeout):
        conn = _Connection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(benchmark, "_connection_for", fake_connection)

    result = benchmark.main(
        [
            "--base-url",
            "http://127.0.0.1:5000",
            "--repeat",
            "2",
            "--path",
            "/api/signals?include_total=0",
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert len(connections) == 3
    assert [len(conn.requests) for conn in connections] == [1, 1, 2]
    assert "secret-response-body" not in output
    assert "cold" in output
    assert "warm" in output


def test_default_benchmark_paths_include_all_listings():
    from scripts import benchmark_public_read_path as benchmark

    assert any(
        path.startswith("/api/listings?") for path in benchmark.DEFAULT_PATHS
    )
