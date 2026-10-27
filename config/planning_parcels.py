"""Historic GIS codes and reference navigation windows for all 91 Bình Dương units."""
import json
from pathlib import Path

PLANNING_REGIONS = tuple(json.loads(Path(__file__).with_name('planning_regions.json').read_text(encoding='utf8'))['areas'])
PARCEL_AREAS = tuple({key:region[key] for key in ('code','ward','city','district')} for region in PLANNING_REGIONS)
