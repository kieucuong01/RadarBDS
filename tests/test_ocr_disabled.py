import sys
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_radar_cli_does_not_expose_extract_legal_ocr_command():
    import radar

    parser = radar.build_parser()
    help_text = parser.format_help()

    assert "extract-legal-ocr" not in help_text


def test_legal_ocr_module_is_not_shipped_while_disabled():
    assert importlib.util.find_spec("cleansing.legal_ocr") is None
