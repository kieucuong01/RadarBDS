import io
from unittest.mock import patch

import pytest
from PIL import Image


def raster():
    result = io.BytesIO(); Image.new('RGB', (400, 200), 'white').save(result, 'PNG')
    return result.getvalue()


def test_draft_only_retains_coordinate_pairs_and_flags_missing_rows():
    from services.planning_corner_ocr import parse_coordinates
    result = parse_coordinates('NGUYEN VAN PRIVATE\n1 1218730.50 594520.25\n2 1218730,50 594550,25 30.00\n3 12I8760.50 594550.25\n4 1218760.50 594520.25', 'vn2000')
    assert result['text'] == '1218730.50 594520.25\n1218730.50 594550.25\n1218760.50 594520.25'
    assert result['warnings'] and 'PRIVATE' not in str(result)


def test_wgs84_and_grouped_vn2000_numbers_are_unambiguous():
    from services.planning_corner_ocr import parse_coordinates
    assert parse_coordinates('1 11.02 106.61\n2 11.03 106.62\n3 11.04 106.63', 'wgs84')['count'] == 3
    assert parse_coordinates('1 1.218.730,50 594.520,25', 'vn2000')['text'] == '1218730.50 594520.25'
    assert parse_coordinates('CCCD 012345678901\nSDT 0912345678', 'vn2000')['count'] == 0
    assert parse_coordinates('CCCD 123456 123456', 'vn2000')['count'] == 0


def test_ocr_uses_fixed_stdin_command_and_does_not_save_image():
    from services.planning_corner_ocr import scan
    with patch('services.planning_corner_ocr.shutil.which', return_value='/usr/bin/tesseract'), patch('services.planning_corner_ocr.subprocess.run') as run:
        run.return_value.stdout = b'1 1218730.50 594520.25\n2 1218760.50 594550.25\n3 1218760.50 594520.25'
        run.return_value.returncode = 0
        result = scan(raster(), 'vn2000')
        args, kwargs = run.call_args
        assert args[0][1:3] == ['stdin', 'stdout'] and kwargs.get('shell', False) is False
        assert kwargs['timeout'] <= 25 and kwargs['env']['OMP_THREAD_LIMIT'] == '1'
        assert kwargs['input'].startswith(b'\x89PNG') and result['count'] == 3


def test_rejects_non_raster_oversize_and_invalid_system():
    from services.planning_corner_ocr import scan
    for data, system in [(b'<svg/>', 'vn2000'), (b'x' * 4_000_001, 'vn2000'), (raster(), 'unknown')]:
        with pytest.raises(ValueError): scan(data, system)


def test_timeout_and_busy_fail_closed_without_logging_image():
    from services.planning_corner_ocr import scan, GATE, OCRBusy, OCRUnavailable
    import subprocess
    GATE.acquire()
    try:
        with pytest.raises(OCRBusy): scan(raster(), 'vn2000')
    finally:
        GATE.release()
    with patch('services.planning_corner_ocr.shutil.which', return_value='/usr/bin/tesseract'), patch(
        'services.planning_corner_ocr.subprocess.run', side_effect=subprocess.TimeoutExpired('ocr', 20)):
        with pytest.raises(OCRUnavailable): scan(raster(), 'vn2000')
    assert GATE.acquire(blocking=False); GATE.release()


def test_private_raw_image_route_and_size_guard(tmp_path):
    from flask import Flask
    from services.planning_parcel_catalog import build_catalog, install_catalog
    from services.planning_corner_ocr import OCRBusy
    from tests.test_planning_parcel_catalog import snapshot
    app = Flask('ocr-test')
    install_catalog(app, build_catalog(tmp_path, [snapshot(tmp_path, '25765', 'Tân An', 'Thủ Dầu Một', 33013, 106.61)]))
    client = app.test_client(); url = '/local-planning/parcels/corners/scan.json?system=vn2000'
    with patch('services.planning_corner_ocr.scan', return_value=dict(text='1218730.50 594520.25', count=1, warnings=[])) as scan:
        response = client.post(url, data=raster(), content_type='image/png')
        assert response.status_code == 200 and response.headers['Cache-Control'] == 'private, no-store'
        assert scan.call_args.args[0].startswith(b'\x89PNG')
    assert client.post(url, data=b'x' * 4_000_001, content_type='image/png').status_code == 413
    with patch('services.planning_corner_ocr.scan', side_effect=OCRBusy):
        assert client.post(url, data=raster(), content_type='image/png').status_code == 503
