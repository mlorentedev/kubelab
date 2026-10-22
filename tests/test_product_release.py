"""`toolkit product release-contract`: the contract prod renders is the release's own (IDP-042).

A prod promotion ships `<image>:<version>`, a re-tag of the digest built from the
release commit, so the contract that belongs to prod is `kubelab.yaml` at that
commit, not at whatever commit staging pins (the staging deploy PR can lag or
lead the release). The commit is found through the product's release tag and
then proven: `<image>:<version>` and `<image>:sha-<commit>` must be one digest,
so a tag naming another commit is refused rather than trusted. `gh` is stubbed
on PATH and the registry lookup is replaced, so every route is observed.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil

import pytest
from typer.testing import CliRunner

from toolkit.cli.product import app
from toolkit.features import product_release

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_CONTRACT = REPO_ROOT / "tests/fixtures/product/web.kubelab.yaml"
FULL = "661a205c0ffee0ddba11ca5cadeba5eba11fade1"
VERSION = "1.16.1"
DIGEST = "sha256:" + "9" * 64

_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"/commits/"*)
      if [ -n "${STUB_COMMIT_ERROR:-}" ]; then echo "gh: No commit found for SHA (HTTP 422)" >&2; exit 1; fi
      printf '%s\\n' "$STUB_SHA" ;;
  *"/contents/kubelab.yaml"*)
      if [ -z "${STUB_CONTRACT:-}" ]; then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi
      cat "$STUB_CONTRACT" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="the gh stub is a bash script")


class _Registry:
    """Registry answers per tag; a test edits ``answers`` to break the proof and reads ``seen``."""

    def __init__(self) -> None:
        self.answers: dict[str, str | None] = {VERSION: DIGEST, f"sha-{FULL[:7]}": DIGEST}
        self.seen: list[tuple[str, str, str]] = []

    def __call__(self, registry: str, image_name: str, tag: str) -> str | None:
        self.seen.append((registry, image_name, tag))
        return self.answers.get(tag)


@pytest.fixture
def digests(monkeypatch: pytest.MonkeyPatch) -> _Registry:
    stub = _Registry()
    monkeypatch.setattr(product_release, "tag_digest", stub)
    return stub


@pytest.fixture
def gh(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "gh").write_text(_GH_STUB)
    (bindir / "gh").chmod(0o755)
    calls = tmp_path / "gh_calls"
    calls.touch()
    monkeypatch.setenv("PATH", os.pathsep.join([str(bindir), os.environ["PATH"]]))
    monkeypatch.setenv("GH_CALLS", str(calls))
    monkeypatch.setenv("STUB_SHA", FULL)
    contract = tmp_path / "kubelab.yaml"
    contract.write_text(WEB_CONTRACT.read_text())
    monkeypatch.setenv("STUB_CONTRACT", str(contract))
    return lambda: calls.read_text().splitlines()


def _fetch(out: pathlib.Path, *argv: str) -> tuple[int, dict]:
    result = CliRunner().invoke(
        app, ["release-contract", "--app", "web", "--version", VERSION, "--out", str(out), *argv, "--json"]
    )
    return result.exit_code, json.loads(result.stdout)


def test_the_release_contract_is_fetched_at_the_tagged_commit(gh, digests, tmp_path: pathlib.Path) -> None:
    out = tmp_path / "snapshots" / "prod" / "web.yaml"

    code, answer = _fetch(out)

    assert code == 0, answer
    assert answer == {
        "ok": True,
        "app": "web",
        "repository": "mlorentedev/web",
        "version": VERSION,
        "sha": FULL,
        "digest": DIGEST,
        "contract": str(out),
    }
    assert out.read_bytes() == WEB_CONTRACT.read_bytes()
    assert gh() == [
        f"api repos/mlorentedev/web/commits/{product_release.RELEASE_TAG_PREFIX}{VERSION} --jq .sha",
        f"api -H Accept: application/vnd.github.raw repos/mlorentedev/web/contents/kubelab.yaml?ref={FULL}",
    ]
    assert digests.seen == [
        ("docker.io/mlorentedev", "kubelab-web", VERSION),
        ("docker.io/mlorentedev", "kubelab-web", f"sha-{FULL[:7]}"),
    ]


def test_the_release_tag_prefix_is_the_one_release_please_cuts() -> None:
    """web tags `v1.16.1` for image `1.16.1`. A wrong prefix is caught by the digest proof, not trusted."""
    assert product_release.RELEASE_TAG_PREFIX == "v"


def test_a_tag_naming_another_commit_is_refused(gh, digests, tmp_path: pathlib.Path) -> None:
    """The image is not the build of the tagged commit: its contract is not prod's."""
    digests.answers[f"sha-{FULL[:7]}"] = "sha256:" + "1" * 64
    out = tmp_path / "web.yaml"

    code, answer = _fetch(out)

    assert code == 1
    assert answer["ok"] is False and "digest" in answer["error"]
    assert not out.exists(), "a refused contract must leave nothing to commit"


@pytest.mark.parametrize("missing", [VERSION, f"sha-{FULL[:7]}"])
def test_an_unreadable_digest_is_refused_not_skipped(gh, digests, tmp_path: pathlib.Path, missing: str) -> None:
    """No proof is not a pass: prod would render a contract nobody tied to the image."""
    digests.answers[missing] = None

    code, answer = _fetch(tmp_path / "web.yaml")

    assert code == 1
    assert answer["ok"] is False and missing in answer["error"]


def test_a_version_with_no_release_tag_is_refused(gh, digests, tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setenv("STUB_COMMIT_ERROR", "1")

    code, answer = _fetch(tmp_path / "web.yaml")

    assert code == 1
    assert f"{product_release.RELEASE_TAG_PREFIX}{VERSION}" in answer["error"]
    assert "HTTP 422" in answer["why"]


def test_a_release_without_a_contract_is_refused(gh, digests, tmp_path: pathlib.Path, monkeypatch) -> None:
    """A rollback to a release older than its kubelab.yaml cannot render prod (ADR-067)."""
    monkeypatch.setenv("STUB_CONTRACT", "")
    out = tmp_path / "web.yaml"

    code, answer = _fetch(out)

    assert code == 1
    assert "kubelab.yaml" in answer["error"] and FULL in answer["error"]
    assert not out.exists()


def test_a_contract_the_registry_refuses_is_not_written(gh, digests, tmp_path: pathlib.Path, monkeypatch) -> None:
    widened = tmp_path / "widened.yaml"
    widened.write_text(WEB_CONTRACT.read_text().replace("mlorentedev/kubelab-web", "someone/else"))
    monkeypatch.setenv("STUB_CONTRACT", str(widened))
    out = tmp_path / "web.yaml"

    code, answer = _fetch(out)

    assert code == 1
    assert answer["ok"] is False
    assert not out.exists()


def test_an_in_tree_product_has_no_release_contract(gh, digests, tmp_path: pathlib.Path) -> None:
    result = CliRunner().invoke(
        app, ["release-contract", "--app", "api", "--version", "1.1.6", "--out", str(tmp_path / "x"), "--json"]
    )

    assert result.exit_code == 1
    assert "in-tree" in json.loads(result.stdout)["error"]
    assert gh() == [], "an in-tree product must not reach the forge"
