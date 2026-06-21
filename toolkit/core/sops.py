"""Resolve the SOPS age-key location so decryption works without per-shell setup.

SOPS looks for the age key at its platform-default path
(``~/.config/sops/age/keys.txt`` on Linux/macOS, ``%APPDATA%\\sops\\age\\keys.txt``
on Windows). This repo's key lives at ``~/.config/age/key.txt``, so unless
``SOPS_AGE_KEY_FILE`` is exported, a fresh shell — ``make test``, a cold deploy,
the agent harness, a new clone — fails to decrypt with a cryptic
"failed to get the data key" error.

``age_key_env()`` augments an environment with ``SOPS_AGE_KEY_FILE`` pointing at
the first key it finds, so every sops subprocess in the toolkit is self-sufficient
regardless of shell configuration. An already-set, existing ``SOPS_AGE_KEY_FILE``
is always honored first (the override; CI sets it to the ci key); if no key is
found the environment is returned unchanged and sops emits its own failure.
"""

import os
from pathlib import Path


def _candidate_key_paths(env: dict[str, str]) -> list[Path]:
    """Conventional age-key locations, most-standard first."""
    home = Path.home()
    candidates = [home / ".config" / "sops" / "age" / "keys.txt"]  # sops default (Linux/macOS)
    appdata = env.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "sops" / "age" / "keys.txt")  # sops default (Windows)
    candidates.append(home / ".config" / "age" / "key.txt")  # repo convention
    return candidates


def resolve_age_key_file(env: dict[str, str] | None = None) -> str | None:
    """Return a path to an existing age key, or None if none is found.

    Honors an already-set, existing ``SOPS_AGE_KEY_FILE`` first (the override),
    then probes the platform-default and repo-convention locations.
    """
    src = env if env is not None else dict(os.environ)
    explicit = src.get("SOPS_AGE_KEY_FILE")
    if explicit and Path(explicit).expanduser().is_file():
        return explicit
    for candidate in _candidate_key_paths(src):
        if candidate.is_file():
            return str(candidate)
    return None


def age_key_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Copy ``base_env`` (default ``os.environ``) with ``SOPS_AGE_KEY_FILE`` set if
    a key is discoverable; otherwise return it unchanged."""
    env = dict(base_env if base_env is not None else os.environ)
    key = resolve_age_key_file(env)
    if key:
        env["SOPS_AGE_KEY_FILE"] = key
    return env
