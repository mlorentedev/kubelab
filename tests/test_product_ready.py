"""`toolkit product ready`: the gate before a product moves to the generic receiver (IDP-042 AC4).

Once a product is `receiver: generic`, every image dispatch fetches `kubelab.yaml`
at the image's commit and refuses an image without one, so staging stalls on the
first push after the flip. This asks the same question once, before the flip, at
the commit staging runs now. `gh` is stubbed on PATH and logs every call, so the
route is observed rather than declared.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil

import pytest
from typer.testing import CliRunner

from toolkit.cli.product import app
from toolkit.features import promotion

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WEB_CONTRACT = REPO_ROOT / "tests/fixtures/product/web.kubelab.yaml"
FULL = "b9874f2f693dd41ee4e1985cb88b0645ac59f996"
TAG = "sha-b9874f2"

_GH_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_CALLS"
case "$*" in
  *"/commits/"*)
      if [ -n "${STUB_COMMIT_ERROR:-}" ]; then echo "gh: No commit found (HTTP 422)" >&2; exit 1; fi
      printf '%s\\n' "$STUB_SHA" ;;
  *"/contents/kubelab.yaml"*)
      if [ -z "${STUB_CONTRACT:-}" ]; then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi
      cat "$STUB_CONTRACT" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="the gh stub is a bash script")


@pytest.fixture
def gh(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """Put the stub first on PATH; return a reader for the calls it received."""
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
    monkeypatch.setattr(promotion, "resolve_image_sha", lambda env, name: TAG)
    return lambda: calls.read_text(encoding="utf-8").splitlines()


def _ready(*argv: str):
    result = CliRunner().invoke(app, ["ready", *argv, "--json"])
    return result.exit_code, json.loads(result.stdout)


def test_a_product_whose_pinned_commit_carries_a_valid_contract_is_ready(gh) -> None:
    code, answer = _ready("--app", "web")

    assert code == 0, answer
    assert answer == {"ok": True, "app": "web", "repository": "mlorentedev/web", "tag": TAG, "sha": FULL}
    assert gh() == [
        "api repos/mlorentedev/web/commits/b9874f2 --jq .sha",
        f"api -H Accept: application/vnd.github.raw repos/mlorentedev/web/contents/kubelab.yaml?ref={FULL}",
    ]


def test_no_contract_at_the_pinned_commit_is_not_ready(gh, monkeypatch: pytest.MonkeyPatch) -> None:
    """The case the gate exists for: the contract merged after the image staging runs."""
    monkeypatch.delenv("STUB_CONTRACT")
    code, answer = _ready("--app", "web")

    assert code == 1
    assert answer["ok"] is False
    assert "kubelab.yaml" in answer["error"] and TAG in answer["error"]
    assert answer["why"] and answer["fix"]


def test_an_invalid_contract_at_the_pinned_commit_is_not_ready(gh, tmp_path: pathlib.Path) -> None:
    (tmp_path / "kubelab.yaml").write_text(
        WEB_CONTRACT.read_text(encoding="utf-8").replace("port: 8080", "port: 0"), encoding="utf-8"
    )
    code, answer = _ready("--app", "web")

    assert code == 1
    assert answer["ok"] is False and answer["why"] and answer["fix"]


def test_a_contract_for_another_product_is_not_ready(gh, tmp_path: pathlib.Path) -> None:
    """Valid by schema, refused by the registry: the check is the receiver's, not the schema's."""
    (tmp_path / "kubelab.yaml").write_text(
        WEB_CONTRACT.read_text(encoding="utf-8").replace("mlorentedev/kubelab-web", "mlorentedev/kubelab-api"),
        encoding="utf-8",
    )
    code, answer = _ready("--app", "web")

    assert code == 1
    assert answer["ok"] is False


@pytest.mark.parametrize(
    "env",
    [{"STUB_COMMIT_ERROR": "1"}, {"STUB_SHA": "0" * 40}, {"STUB_SHA": "b9874f2"}],
    ids=["unresolvable", "another-commit", "not-a-full-sha"],
)
def test_a_pin_that_names_no_single_commit_is_not_ready(
    gh, monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    code, answer = _ready("--app", "web")

    assert code == 1
    assert answer["ok"] is False
    assert not [call for call in gh() if "/contents/" in call], "a contract was fetched for no commit"


@pytest.mark.parametrize("name", ["api", "ghost"])
def test_a_product_with_no_contract_to_check_asks_nothing(gh, name: str) -> None:
    """In-tree and unregistered products are refused before any network call."""
    code, answer = _ready("--app", name)

    assert code == 1
    assert answer["ok"] is False
    assert gh() == []


def test_the_text_form_prints_the_three_lines_on_stderr(gh, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUB_CONTRACT")
    result = CliRunner().invoke(app, ["ready", "--app", "web"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert [line.split(":", 1)[0] for line in result.stderr.splitlines()] == ["ERROR", "WHY", "FIX"]


def test_a_product_on_another_forge_asks_github_nothing(gh, tmp_path: pathlib.Path) -> None:
    """A Gitea repository name sent to `gh api` would be answered by GitHub, about someone else's repository."""
    from toolkit.features import product_ready
    from toolkit.features.product_contract import ContractError

    registry = tmp_path / "registry.yaml"
    registry.write_text(
        (REPO_ROOT / "tests/fixtures/product/registry.yaml").read_text(encoding="utf-8")
        + "  forged:\n    repository: mlorentedev/forged\n    forge: gitea\n    receiver: generic\n"
        "    events:\n      staging: forged-image-published\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="forge: gitea"):
        product_ready.check_ready("forged", registry=registry)
    assert gh() == []
