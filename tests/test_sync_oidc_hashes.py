"""Regression tests for sync_oidc_hashes — guards path drift + silent no-op.

OIDC-SYNC-001: PR #225 moved the OIDC clients out of authelia.yaml / patches.yaml
into authelia-config/configuration.yml, but FILE_PATHS still pointed at the old
files. The script then reported ``OK: ... already current`` while doing nothing, so
prod Gitea OIDC drifted undetected until a manual smoke caught ``invalid_client``.

These tests fail loudly if either regression returns:
  1. FILE_PATHS points at a file that has no ``client_secret:`` line (path drift).
  2. ``update_client_secret`` silently returns unchanged content on a regex miss.
"""

from __future__ import annotations

import pytest

from toolkit.scripts.sync_oidc_hashes import (
    FILE_PATHS,
    OIDC_CLIENTS,
    update_client_secret,
)

# Structurally valid argon2id shape, not a real secret — only used in-memory.
_SAMPLE_HASH = "$argon2id$v=19$m=65536,t=3,p=4$TESTSALT$TESTHASHTESTHASHTESTHASHTESTHASH00"


class TestFilePaths:
    """Every FILE_PATHS target must actually contain OIDC client secrets."""

    @pytest.mark.parametrize("key", sorted(FILE_PATHS))
    def test_target_exists_and_has_client_secret(self, key: str) -> None:
        path = FILE_PATHS[key]
        assert path.exists(), f"FILE_PATHS['{key}'] does not exist: {path}"
        assert "client_secret:" in path.read_text(), (
            f"FILE_PATHS['{key}'] ({path}) has no 'client_secret:' line — path drift "
            "would make sync_oidc_hashes a silent no-op (OIDC-SYNC-001)."
        )


class TestUpdateClientSecret:
    """Replace on match; raise (never silently no-op) on miss."""

    def test_replaces_existing_secret(self) -> None:
        content = (
            "clients:\n"
            "  - client_id: gitea\n"
            "    client_name: Gitea\n"
            "    client_secret: 'OLDHASH'\n"
            "    public: false\n"
        )
        result = update_client_secret(content, "gitea", _SAMPLE_HASH)
        assert _SAMPLE_HASH in result
        assert "OLDHASH" not in result

    def test_raises_when_client_missing(self) -> None:
        content = "clients:\n  - client_id: minio\n    client_secret: 'X'\n"
        with pytest.raises(RuntimeError, match="not found"):
            update_client_secret(content, "gitea", _SAMPLE_HASH)


def test_managed_clients_resolve_in_repo_configs() -> None:
    """The direct OIDC-SYNC-001 guard: run the real regex against the real files.

    For every managed client, in every file it claims to live in, the secret must be
    found and replaced. This is exactly the check that the broken FILE_PATHS bypassed.
    """
    for sops_path, info in OIDC_CLIENTS.items():
        client_id = str(info["client_id"])
        files = info["files"]
        assert isinstance(files, list)
        for file_key in files:
            key = str(file_key)
            content = FILE_PATHS[key].read_text()
            updated = update_client_secret(content, client_id, _SAMPLE_HASH)
            assert updated != content, (
                f"client '{client_id}' ({sops_path}) not updated in "
                f"FILE_PATHS['{key}'] ({FILE_PATHS[key]}) — regex/path drift "
                "(OIDC-SYNC-001)."
            )
            assert _SAMPLE_HASH in updated
