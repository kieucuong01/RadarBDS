"""Scan tracked text files for high-confidence credential formats.

Findings deliberately retain only rule, path, and line number. Matched values
must never enter process output, logs, exceptions, or returned objects.
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
RULES = (
    (
        "private_key",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    ),
    (
        "github_fine_grained_pat",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b"),
    ),
    (
        "github_pat",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
    ),
    (
        "aws_access_key_id",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        "slack_token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,255}\b"),
    ),
    (
        "google_api_key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
)


@dataclass(frozen=True, order=True)
class Finding:
    path: Path
    line: int
    rule: str


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    findings: set[Finding] = set()
    for supplied_path in paths:
        path = Path(supplied_path)
        try:
            payload = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError, OSError):
            continue
        if b"\x00" in payload:
            continue
        text = payload.decode("utf-8", errors="replace")
        for rule, pattern in RULES:
            for match in pattern.finditer(text):
                findings.add(
                    Finding(
                        path=path,
                        line=text.count("\n", 0, match.start()) + 1,
                        rule=rule,
                    )
                )
    return sorted(findings, key=lambda item: (str(item.path), item.line, item.rule))


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def render_findings(findings: Iterable[Finding]) -> str:
    return "\n".join(
        f"{_display_path(finding.path)}:{finding.line}:{finding.rule}"
        for finding in findings
    )


def tracked_paths(root: Path = ROOT) -> list[Path]:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.resolve().as_posix()}",
            "ls-files",
            "-z",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = completed.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    return [root / name for name in names if name]


def main() -> int:
    try:
        paths = tracked_paths()
    except (OSError, subprocess.CalledProcessError):
        print("tracked-secret scan failed: git file list unavailable", file=sys.stderr)
        return 2
    findings = scan_paths(paths)
    if findings:
        print(render_findings(findings))
        return 1
    print(f"tracked-secret scan passed: {len(paths)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
