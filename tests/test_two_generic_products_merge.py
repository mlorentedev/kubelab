"""Two products' long-lived deploy PRs rewrite the same files and still merge in either order (#2611).

Every product promoted to staging keeps its own `deploy/staging-<app>` branch, and each one rewrites
the same two files: `values/staging.yaml` and the generated staging overlay. Each branch is cut from
master's tip when its image lands, so the second PR to merge is a three-way merge of its branch onto a
master that already holds the first. These tests run that merge with git, in both orders. A conflict
would hold the PR until its next image; a stale copy of the other product's pin would downgrade it.

The values file is written by the real `promotion.promote` (the overlay generator is stubbed) for two
generic products laid out as tightly as the writer allows. The overlay is the committed staging file,
with each app's image line changed as its deploy PR changes it: one line per app.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest
import yaml

from toolkit.features import product_registry, product_render, promotion
from toolkit.features.product_contract import validate_contract

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "infra/k8s/overlays/staging/generated/deployments.yaml"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="the merge is git's")

REGISTRY = """\
products:
  web:
    repository: mlorentedev/web
    forge: github
    receiver: generic
    image_name: kubelab-web
    events: {staging: web-image-published}
  third:
    repository: mlorentedev/third
    forge: github
    receiver: generic
    events: {staging: third-image-published}
"""

# The tightest layout the writer produces: web's pin is its block's last line, and a product
# promoted for the first time gets its pin inserted first, so only `third:` separates the two.
VALUES = """\
apps:
  platform:
    web:
      domain: staging.mlorente.dev
      version: sha-1111111
    third:
      version: sha-3333333
      domain: third.staging.kubelab.live

  # Third-party services
  services: {}
"""


def _merge(base: str, ours: str, theirs: str, tmp: pathlib.Path) -> tuple[int, str]:
    """`git merge-file`: the same three-way text merge a pull request's merge performs."""
    paths = {}
    for name, text in (("base", base), ("ours", ours), ("theirs", theirs)):
        paths[name] = tmp / name
        paths[name].write_text(text, encoding="utf-8")
    done = subprocess.run(
        ["git", "merge-file", "-p", str(paths["ours"]), str(paths["base"]), str(paths["theirs"])],
        capture_output=True,
        encoding="utf-8",
    )
    # Exit status is the number of conflicts; a negative one is an error.
    return done.returncode, done.stdout


def _changed_lines(before: str, after: str) -> list[str]:
    return [b for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]


@pytest.fixture
def promote_into(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    registry = tmp_path / "products.yaml"
    registry.write_text(REGISTRY, encoding="utf-8")
    monkeypatch.setattr(product_registry, "registry_path", lambda: registry)
    monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
    monkeypatch.setattr(promotion, "K8sGenerator", MagicMock())
    cm = MagicMock()
    cm.return_value.get_env_vars.return_value = {
        "REGISTRY": "docker.io/mlorentedev",
        "APPS_PLATFORM_WEB_IMAGE_NAME": "kubelab-web",
        "APPS_PLATFORM_THIRD_IMAGE_NAME": "third",
    }
    monkeypatch.setattr(promotion, "ConfigurationManager", cm)

    def run(app: str, tag: str) -> str:
        """Promote ``app`` on a fresh copy of the base, as its receiver does on master's tip."""
        root = tmp_path / f"{app}-{tag}"
        values = root / "infra/config/values/staging.yaml"
        values.parent.mkdir(parents=True)
        values.write_text(VALUES, encoding="utf-8")
        monkeypatch.setattr(promotion, "settings", MagicMock(project_root=root))
        promotion.promote("staging", app, tag)
        return values.read_text(encoding="utf-8")

    return run


def test_each_deploy_pr_writes_only_its_own_pin(promote_into) -> None:
    web = promote_into("web", "sha-2222222")
    third = promote_into("third", "sha-4444444")
    assert _changed_lines(VALUES, web) == ["      version: sha-2222222"]
    assert _changed_lines(VALUES, third) == ["      version: sha-4444444"]


@pytest.mark.parametrize("first", ["web", "third"])
def test_values_merge_cleanly_in_either_order_and_keep_both_pins(
    promote_into, tmp_path: pathlib.Path, first: str
) -> None:
    branches = {"web": promote_into("web", "sha-2222222"), "third": promote_into("third", "sha-4444444")}
    second = "third" if first == "web" else "web"
    # master after the first merge is that branch; the second PR merges onto it.
    conflicts, merged = _merge(VALUES, branches[first], branches[second], tmp_path)
    assert conflicts == 0, merged
    platform = yaml.safe_load(merged)["apps"]["platform"]
    assert platform["web"]["version"] == "sha-2222222"
    assert platform["third"]["version"] == "sha-4444444"


@pytest.fixture
def real_values_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path):
    """A receiver run on the committed staging values: render the contract, then promote the tag."""
    monkeypatch.setattr(promotion, "tag_exists", MagicMock(return_value=True))
    monkeypatch.setattr(promotion, "K8sGenerator", MagicMock())
    cm = MagicMock()
    cm.return_value.get_env_vars.return_value = {
        "REGISTRY": "docker.io/mlorentedev",
        "APPS_PLATFORM_WEB_IMAGE_NAME": "kubelab-web",
        "APPS_PLATFORM_API_IMAGE_NAME": "kubelab-api",
    }
    monkeypatch.setattr(promotion, "ConfigurationManager", cm)

    def run(app: str, tag: str, contract: str | None = None) -> str:
        root = tmp_path / app
        values_dir = root / "infra/config/values"
        shutil.copytree(product_render.VALUES_DIR, values_dir)
        if contract is not None:
            snapshot = root / "contract.yaml"
            snapshot.write_text(contract, encoding="utf-8")
            assert product_render.write(validate_contract(snapshot), app, "staging", values_dir=values_dir)
        monkeypatch.setattr(promotion, "settings", MagicMock(project_root=root))
        promotion.promote("staging", app, tag)
        return (values_dir / "staging.yaml").read_text(encoding="utf-8")

    return run


@pytest.mark.parametrize("first", ["web", "api"])
def test_a_contract_render_and_a_pin_merge_cleanly_with_another_products_pin(
    real_values_branch, tmp_path, first
) -> None:
    # web's PR also carries a contract change, which `render --write` writes into web's block
    # before the pin moves. Both writers edit only inside `apps.platform.<app>`.
    contract = product_render.snapshot_path("web", "staging").read_text(encoding="utf-8")
    assert "port: 8080" in contract
    branches = {
        "web": real_values_branch("web", "sha-2222222", contract.replace("port: 8080", "port: 9090")),
        "api": real_values_branch("api", "sha-4444444"),
    }
    base = (product_render.VALUES_DIR / "staging.yaml").read_text(encoding="utf-8")
    second = "api" if first == "web" else "web"
    conflicts, merged = _merge(base, branches[first], branches[second], tmp_path)
    assert conflicts == 0, merged
    platform = yaml.safe_load(merged)["apps"]["platform"]
    assert (platform["web"]["version"], platform["web"]["default_port"]) == ("sha-2222222", 9090)
    assert platform["api"]["version"] == "sha-4444444"


def test_the_merge_does_report_a_conflict(tmp_path: pathlib.Path) -> None:
    # Control: two pins on consecutive lines DO conflict, so a clean merge above is a finding,
    # not a merge that cannot fail. The `<app>:` key between two blocks is what keeps them apart.
    base = "a: sha-1111111\nb: sha-3333333\n"
    conflicts, _ = _merge(base, "a: sha-2222222\nb: sha-3333333\n", "a: sha-1111111\nb: sha-4444444\n", tmp_path)
    assert conflicts == 1


def _repin(text: str, image: str, tag: str) -> str:
    out, n = re.subn(rf"(image: \S+/{re.escape(image)}:)\S+", rf"\g<1>{tag}", text)
    assert n == 1, f"{image}: expected one image line in the overlay, found {n}"
    return out


@pytest.mark.parametrize("first", ["kubelab-web", "kubelab-api"])
def test_the_overlay_merges_cleanly_in_either_order(tmp_path: pathlib.Path, first: str) -> None:
    base = OVERLAY.read_text(encoding="utf-8")
    branches = {name: _repin(base, name, "sha-9999999") for name in ("kubelab-web", "kubelab-api")}
    second = "kubelab-api" if first == "kubelab-web" else "kubelab-web"
    conflicts, merged = _merge(base, branches[first], branches[second], tmp_path)
    assert conflicts == 0, merged
    assert merged.count(":sha-9999999") == 2
