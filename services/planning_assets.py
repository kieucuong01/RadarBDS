"""Validate the immutable public planning snapshot once when each web worker starts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def release_id(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]


def load_release(site):
    try:
        site = Path(site)
        config = json.loads((site/'config/planning_release.json').read_text(encoding='utf8'))
        version, files = config['release'], config['files']
        if not re.fullmatch(r'[a-f0-9]{16}', version) or not isinstance(files, dict) or not 1 <= len(files) <= 129:
            return None
        if 'catalog.json' not in files or release_id(files) != version:
            return None
        base = (site/'static/maps/planning/overlays'/version).resolve()
        for name, expected in files.items():
            if not re.fullmatch(r'(catalog\.json|[a-z0-9-]+/(overlay|legend)\.webp)', name):
                return None
            path = (base/name).resolve()
            if not path.is_relative_to(base) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return None
        prefix = '/static/maps/planning/overlays/' + version + '/'
        return {'catalogUrl': prefix+'catalog.json', 'assetBase': prefix}
    except (OSError, ValueError, KeyError, TypeError):
        return None
