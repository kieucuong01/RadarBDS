import pytest

from cli.notify import _notification_event


@pytest.mark.parametrize('price,status,expected', [
    (1.995, 'active', 'price_drop'),  # Exactly 5% despite binary float rounding.
    (2.05, 'active', None),
    (1.8, 'unreachable', None),
    (0.9, 'active', None),  # Implausible drop requires QC.
    (float('nan'), 'active', None),
    (0, 'active', None),
])
def test_only_meaningful_price_changes_alert(price, status, expected):
    listing = {'price_ty': price, 'source_status': status, 'alert_listing_eligible': 1}
    previous = {'notified_price_ty': 2.1, 'notified_source_status': 'active'}
    assert _notification_event(listing, previous, allow_new=False) == expected


def test_new_signal_from_inactive_source_does_not_alert():
    assert _notification_event({'alert_signal_eligible': 1, 'source_status': 'inactive'}, None) is None
