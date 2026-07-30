import os

from config import settings


def test_env_local_overrides_base_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("RADAR_ENV_TEST_VALUE", raising=False)
    base = tmp_path / ".env"
    local = tmp_path / ".env.local"
    base.write_text("RADAR_ENV_TEST_VALUE=production\n", encoding="utf-8")
    local.write_text("RADAR_ENV_TEST_VALUE=local\n", encoding="utf-8")

    settings._load_dotenv(base)
    settings._load_dotenv(local, override=True)

    assert os.environ["RADAR_ENV_TEST_VALUE"] == "local"
