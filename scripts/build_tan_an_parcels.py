"""Capture the bounded public Tân An parcel pilot, without private owner fields."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    from services.planning_parcels import capture
    capture(ROOT/'.local/planning-parcels-tan-an')
