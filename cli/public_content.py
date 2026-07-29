"""CLI entrypoint for the deterministic public-content collector."""

from __future__ import annotations

import json

from db.connection import advisory_lock
from db.schema import init_schema
from services.public_content import run_public_content_sync


def cmd_public_content_sync(args) -> dict:
    init_schema()
    with advisory_lock("public-content-sync"):
        summary = run_public_content_sync(kind=args.kind)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return summary
