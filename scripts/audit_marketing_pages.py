"""Command-line entrypoint for the deterministic public marketing audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.marketing_page_audit import audit_marketing_pages, render_human


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Radar BDS marketing pages")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    result = audit_marketing_pages(strict=args.strict)
    output = json.dumps(result.to_dict(args.limit), ensure_ascii=False, indent=2) if args.as_json else render_human(result)
    print(output)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
