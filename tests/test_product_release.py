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

    def __call__(self, registry: str, image_name: str, tag: str, credential=None, http=None) -> str | None:
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
    (bindir / "gh").write_text(_GH_STUB, encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    calls = tmp_path / "gh_calls"
    calls.touch()
    monkeypatch.setenv("PATH", os.pathsep.join([str(bindir), os.environ["PATH"]]))
    monkeypatch.setenv("GH_CALLS", str(calls))
    monkeypatch.setenv("STUB_SHA", FULL)
    contract = tmp_path / "kubelab.yaml"
    contract.write_text(WEB_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("STUB_CONTRACT", str(contract))
    return lambda: calls.read_text(encoding="utf-8").splitlines()


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


@pytest.mark.parametrize("length", [7, 10, 40])
def test_the_proof_finds_the_sha_tag_the_product_publishes(gh, digests, tmp_path: pathlib.Path, length: int) -> None:
    """The receiver admits `sha-<7..40 hex>` (#2627), so the proof accepts any prefix of the commit in that range."""
    digests.answers = {VERSION: DIGEST, f"sha-{FULL[:length]}": DIGEST}

    code, answer = _fetch(tmp_path / "web.yaml")

    assert code == 0, answer
    assert digests.seen[-1][2] == f"sha-{FULL[:length]}"
    assert [tag for _, _, tag in digests.seen[1:]] == [f"sha-{FULL[:n]}" for n in range(7, length + 1)]


def test_a_missing_release_tag_reads_no_sha_tag(gh, digests, tmp_path: pathlib.Path) -> None:
    """An unreadable `<version>` already decides the refusal: the sha search is not run behind it."""
    digests.answers[VERSION] = None

    code, _ = _fetch(tmp_path / "web.yaml")

    assert code == 1
    assert [tag for _, _, tag in digests.seen] == [VERSION]


def test_an_unread_release_tag_names_a_private_repository_as_a_cause(gh, digests, tmp_path: pathlib.Path) -> None:
    """Docker Hub answers a private repository like an absent tag; the message says so (#2627)."""
    digests.answers[VERSION] = None

    _, answer = _fetch(tmp_path / "web.yaml")

    assert "private" in answer["why"]


def test_a_private_registry_without_its_credential_is_refused_by_name(
    gh, digests, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not 'check that the tag exists': the tag may exist where the proof has no login to look (#2627 AC2)."""
    private = product_release.product_registry.Product(
        forge="github",
        repository="mlorentedev/web",
        receiver="generic",
        private=True,
        image_registry="ghcr.io/acme",
        pull_credential={"username": "deploy-bot", "secret": "ghcr.pull_token"},
    )
    monkeypatch.setattr(product_release.product_registry, "product", lambda app, registry=None: private)
    monkeypatch.setattr(product_release, "catalog_secret", lambda key: None)

    code, answer = _fetch(tmp_path / "web.yaml")

    assert code == 1
    assert "ghcr.io/acme" in answer["error"] and "ghcr.pull_token" in answer["error"]
    assert "exists" not in answer["fix"]
    assert digests.seen == [], "a private registry with no credential must be refused before any read"


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
    widened.write_text(
        WEB_CONTRACT.read_text(encoding="utf-8").replace("mlorentedev/kubelab-web", "someone/else"), encoding="utf-8"
    )
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
