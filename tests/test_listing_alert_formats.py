"""Delivery format checks use mocks only; never contact notification providers."""
import html
import re
from unittest.mock import patch


def test_email_updates_escape_content_and_use_absolute_links():
    from alerts.email import send_listing_alert
    listing = {'id': 42, 'title': '<script>bad</script>', 'ward': 'Phú Lợi',
               'price_ty': 1.8, 'mos_pct': 20, '_notification_event': 'source_removed'}
    with patch('alerts.email._smtp_config', return_value={'dry_run': False}), \
         patch('alerts.email._is_configured', return_value=True), \
         patch('alerts.email.send_email', return_value=True) as send:
        assert send_listing_alert('test@example.test', '<name>', [listing])
    markup = send.call_args.args[2]
    assert '<script>' not in markup
    assert '&lt;script&gt;' in markup
    assert 'chưa xác nhận đã bán' in markup
    assert 'https://radarbds.vn/listing/42' in markup
    assert '&lt;name&gt;' in markup


def test_dry_runs_do_not_acknowledge_delivery():
    from alerts.email import send_listing_alert
    from alerts.telegram import send_watchlist_digest
    with patch('alerts.email._smtp_config', return_value={'dry_run': True}), \
         patch('alerts.email.send_email') as send:
        assert not send_listing_alert('test@example.test', None, [{'id': 42}])
        send.assert_not_called()
    with patch.dict('os.environ', {'TELEGRAM_DRY_RUN': '1'}), \
         patch('alerts.telegram.send_message_to') as send:
        assert not send_watchlist_digest('mock-chat', [{'id': 42}])
        send.assert_not_called()


def test_telegram_status_digest_fits_provider_limit():
    from alerts.telegram import send_watchlist_digest
    listings = [{'id': i, 'title': '<&>' * 100, 'ward': '&' * 120, 'property_type': 'dat_nen',
                 'price_ty': 2, 'area_m2': 100, 'mos_pct': 20,
                 '_notification_event': 'source_removed'} for i in range(6)]
    with patch.dict('os.environ', {'TELEGRAM_DRY_RUN': '0'}), \
         patch('alerts.telegram.send_message_to', return_value=True) as send:
        assert send_watchlist_digest('mock-chat', listings, base_url='https://radarbds.vn',
                                     watchlist_names=['&' * 300] * 3)
    text = send.call_args.args[1]
    assert 'chưa xác nhận đã bán' in text
    assert len(html.unescape(re.sub(r'<[^>]*>', '', text))) <= 4096
