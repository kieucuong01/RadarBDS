import subprocess
import sys


def test_admin_duplicate_qc_import_does_not_load_flask_transport():
    script = """
import sys
import services.admin_duplicate_qc
assert "app" not in sys.modules
assert not any(name == "flask" or name.startswith("flask.") for name in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
