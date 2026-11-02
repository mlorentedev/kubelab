"""Tests for toolkit.core.io — Windows-safe generated-file writes (TOOL-020).

`Path.write_text()` with no `newline=` translates `\n` -> `os.linesep` on
write, so the same generator produces CRLF on Windows and LF on Linux/CI.
The byte-level drift comparator in `toolkit/cli/sync.py` then reports a
platform difference as SSOT drift. `write_text_lf` pins both the newline
and the encoding so every generated file is byte-identical across hosts.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from toolkit.core.io import docker_user_args, write_text_lf


class TestWriteTextLf:
    def test_writes_lf_only_regardless_of_host_os(self, tmp_path: Path) -> None:
        target = tmp_path / "generated.yaml"
        write_text_lf(target, "line one\nline two\nline three\n")

        raw = target.read_bytes()
        assert b"\r" not in raw

    def test_content_matches_utf8_encoding_exactly(self, tmp_path: Path) -> None:
        target = tmp_path / "generated.yaml"
        content = "arrow: →\nname: café\n"
        write_text_lf(target, content)

        assert target.read_bytes() == content.encode("utf-8")

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "generated.yaml"
        target.write_text("old content", encoding="utf-8")

        write_text_lf(target, "new content\n")

        assert target.read_bytes() == b"new content\n"


class TestDockerUserArgs:
    def test_runs_the_container_as_the_caller_where_uids_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
        monkeypatch.setattr(os, "getgid", lambda: 1001, raising=False)

        assert docker_user_args() == ["--user", "1000:1001"]

    def test_passes_no_user_where_the_host_has_no_uids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Native Windows has no os.getuid; Docker Desktop bind mounts carry no uid ownership to match."""
        monkeypatch.delattr(os, "getuid", raising=False)
        monkeypatch.delattr(os, "getgid", raising=False)

        assert docker_user_args() == []
