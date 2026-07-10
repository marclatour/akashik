"""Load environment variables from .env files, stdlib only.

Precedence, highest first: existing process environment, ./.env,
~/.akashik/.env. Values never override what is already set, so a
per-project .env beats the global one and real environment beats both.
"""

from __future__ import annotations

import os
from pathlib import Path


def default_env_paths() -> list[Path]:
    return [Path(".env"), Path.home() / ".akashik" / ".env"]


def load_env(*paths: str | Path) -> list[Path]:
    """Load KEY=VALUE lines into os.environ without overriding existing keys.

    With no arguments, loads ``./.env`` then ``~/.akashik/.env``. Returns the
    files that were actually read. Lines starting with ``#`` and blank lines
    are ignored; an optional ``export `` prefix and single/double quotes
    around the value are stripped.
    """
    candidates = [Path(p).expanduser() for p in paths] if paths else default_env_paths()
    loaded: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :]
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
        loaded.append(path)
    return loaded
