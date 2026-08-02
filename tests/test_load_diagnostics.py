import json
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS_MODULE = (
    REPO_ROOT / "scripts" / "load" / "radar_failure_diagnostics.mjs"
)
LOAD_PROBE = REPO_ROOT / "tests" / "js" / "run_load_failure_probe.mjs"


def _run_diagnostic_module(script: str):
    node = shutil.which("node")
    assert node, "Node.js is required for load diagnostic contract tests"
    result = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_failure_diagnostic_reports_only_safe_boundary_metadata():
    module_url = DIAGNOSTICS_MODULE.as_uri()
    actual = _run_diagnostic_module(
        f"""
        const {{ buildFailureDiagnostic }} = await import({json.dumps(module_url)});
        const success = buildFailureDiagnostic('signals', {{
          status: 200,
          headers: {{ 'CF-Ray': 'success-ray' }},
          body: 'must not be logged',
        }});
        const failure = buildFailureDiagnostic('signals', {{
          status: 522,
          error_code: 1211,
          headers: {{
            'CF-Ray': 'a24e-example-HKG',
            'CF-Cache-Status': 'DYNAMIC',
            'CF-Error-Type': '502',
            'CF-Error-Origin': 'edge',
            'X-Radar-Edge-Cache': '',
          }},
          body: 'phone=0909000000&source_url=private',
        }});
        console.log(JSON.stringify({{ success, failure }}));
        """
    )

    assert actual == {
        "success": None,
        "failure": {
            "endpoint": "signals",
            "status": 522,
            "error_code": 1211,
            "cf_ray": "a24e-example-HKG",
            "cf_cache": "DYNAMIC",
            "cf_error_type": "502",
            "cf_error_origin": "edge",
            "radar_cache": "",
        },
    }


def test_k6_load_harness_emits_bounded_failure_diagnostic():
    node = shutil.which("node")
    assert node, "Node.js is required for load diagnostic contract tests"
    result = subprocess.run(
        [node, "--experimental-vm-modules", str(LOAD_PROBE)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr

    expected_warning = (
        'radar_http_failure={"endpoint":"signals","status":522,'
        '"error_code":1211,"cf_ray":"probe-ray-HKG",'
        '"cf_cache":"","cf_error_type":"522",'
        '"cf_error_origin":"edge","radar_cache":""}'
    )
    actual = json.loads(result.stdout)
    assert actual["warnings"] == [
        expected_warning,
        expected_warning,
        expected_warning,
    ]
    assert actual["counters"] == {
        "radar_cdn_error": 6,
        "radar_cdn_hit": 10,
        "radar_cdn_unknown": 0,
        "radar_edge_error": 6,
        "radar_edge_hit": 10,
        "radar_edge_unknown": 0,
        "radar_origin_error": 1,
        "radar_transport_error": 0,
    }
