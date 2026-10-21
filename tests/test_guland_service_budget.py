"""Both sequential crawl services own the full postprocessing pipeline."""
from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def service(name):
    config = ConfigParser(interpolation=None)
    assert config.read(ROOT / 'deployment' / 'ubuntu24' / name)
    return config['Service']


def test_guland_full_pipeline_has_primary_startup_budget():
    primary = service('radar-bds-crawl.service')
    secondary = service('radar-bds-guland-crawl.service')
    # Both include reprocess, valuation, maps, images, export and warming.
    # 90m killed Guland 5s after reaching its image phase on 2026-10-21.
    assert secondary['TimeoutStartSec'] == primary['TimeoutStartSec'] == '2h'


def test_guland_budget_fix_preserves_oneshot_lock_and_full_workflow():
    secondary = service('radar-bds-guland-crawl.service')
    assert secondary['Type'] == 'oneshot'
    assert secondary['User'] == 'radar'
    command = secondary['ExecStart']
    assert command.startswith('/usr/bin/flock -n /run/radar-bds/crawl.lock ')
    assert 'radar.py crawl-daily --source guland --no-alert' in command
    assert '--no-reprocess' not in command
    assert '--skip-images' not in command
    assert secondary['TimeoutStartSec'] != 'infinity'
