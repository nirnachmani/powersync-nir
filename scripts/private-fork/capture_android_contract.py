#!/usr/bin/env python3
"""Sanitise a user-owned Android/HA JSON capture into a commit-safe fixture."""

from __future__ import annotations

import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = frozenset({
    "access_token", "authorization", "cookie", "email", "host", "ip_address",
    "password", "refresh_token", "token", "url", "user_id", "vin",
})
IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def _redact_string(value: str) -> str:
    def replace_ip(match: re.Match[str]) -> str:
        try:
            ipaddress.ip_address(match.group(0))
        except ValueError:
            return match.group(0)
        return "[REDACTED]"

    return IPV4_PATTERN.sub(replace_ip, value)


def sanitise(value: Any, key: str | None = None) -> Any:
    """Preserve JSON shape while removing known sensitive values."""
    if key and key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {child_key: sanitise(child_value, child_key) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [sanitise(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} INPUT.json OUTPUT.json", file=sys.stderr)
        return 2
    input_path, output_path = map(Path, argv[1:])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(sanitise(json.loads(input_path.read_text())), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
