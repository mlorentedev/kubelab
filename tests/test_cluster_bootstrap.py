"""Integration check: _load_cluster_bootstrap reads the real common.yaml SSOT (TOOL-009)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import typer
import yaml

from toolkit.cli.infra import _load_cluster_bootstrap
from toolkit.features.k8s_render import BootstrapEntry

ROOT = Path(__file__).resolve().parent.parent
K8S = ROOT / "infra" / "k8s"


def test_loads_expected_entries() -> None:
    names = {e.name for e in _load_cluster_bootstrap()}
    assert {"agent-sandbox", "coredns-custom"} <= names


def test_agent_sandbox_is_versioned_operator() -> None:
    entry = next(e for e in _load_cluster_bootstrap() if e.name == "agent-sandbox")
    assert entry.version  # the pin lives in common.yaml; a bump must not need an edit here
    # The vendored manifest is what gets applied, so its controller image must be the
    # pinned release. A Renovate bump that skips `make sync-operators` leaves the old image.
    manifest = (ROOT / entry.manifest).read_text(encoding="utf-8")
    assert f"agent-sandbox-controller:{entry.version}" in manifest
    assert entry.namespace == "agent-sandbox-system"
    assert entry.render == {}  # static operator — no deploy-time placeholders
    assert entry.optional is False


def test_coredns_is_rendered_and_optional() -> None:
    entry = next(e for e in _load_cluster_bootstrap() if e.name == "coredns-custom")
    assert entry.optional is True  # RPi4 on-demand — skip when off
    assert entry.render == {"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"}
    assert entry.version is None  # config, not a versioned operator


def _kustomize_resources() -> Iterator[tuple[Path, Path]]:
    """(kustomization file, resolved path) for every `resources:` entry under infra/k8s."""
    for kustomization in K8S.rglob("kustomization.yaml"):
        doc = yaml.safe_load(kustomization.read_text(encoding="utf-8")) or {}
        for resource in doc.get("resources") or []:
            yield kustomization, (kustomization.parent / resource).resolve()


def test_the_kustomize_scan_reaches_the_base() -> None:
    """Without this, a moved base would make the guard below pass over nothing."""
    assert any(k == K8S / "base" / "kustomization.yaml" for k, _ in _kustomize_resources())


@pytest.mark.parametrize("entry", _load_cluster_bootstrap(), ids=lambda e: e.name)
def test_a_bootstrap_manifest_is_never_a_kustomize_resource(entry: BootstrapEntry) -> None:
    """The bootstrap layer applies these outside the overlay on purpose (OBS-009).

    The overlays set `namespace: kubelab`, so a manifest listed there is rewritten
    into a second `kubelab` object, and the namespace it was written for (here
    kube-system) silently goes ungoverned. Nothing else fails: the adversarial
    review of OBS-009 added the LimitRange to the base and the whole suite passed.
    """
    manifest = (ROOT / entry.manifest).resolve()
    hits = [
        f"{k.relative_to(ROOT)} lists {r.relative_to(ROOT)}"
        for k, r in _kustomize_resources()
        if r == manifest or (r.is_dir() and not (r / "kustomization.yaml").exists() and manifest.is_relative_to(r))
    ]
    assert not hits, f"{entry.name} is applied by cluster_bootstrap and must not be a Kustomize resource: {hits}"


@pytest.mark.parametrize("dry_run", [False, True])
def test_the_loop_applies_every_entry_in_declared_order(monkeypatch: pytest.MonkeyPatch, dry_run: bool) -> None:
    """`k8s deploy`, `k8s dry-run` and `k8s bootstrap` all run this loop over the SSOT."""
    from toolkit.cli import infra

    seen: list[tuple[str, bool]] = []

    def _record(entry: BootstrapEntry, **kwargs: object) -> bool:
        seen.append((entry.name, bool(kwargs["dry_run"])))
        return True

    monkeypatch.setattr(infra, "render_and_apply", _record)
    assert infra._apply_cluster_bootstrap("/kc", env="staging", dry_run=dry_run) is True
    assert seen == [(e.name, dry_run) for e in _load_cluster_bootstrap()]


def test_the_loop_stops_at_the_first_hard_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later entry may depend on an earlier one (a CRD before its objects), so nothing after a failure runs."""
    from toolkit.cli import infra

    entries = [e.name for e in _load_cluster_bootstrap()]
    assert len(entries) >= 2, "the fail-fast check needs an entry after the failing one"
    seen: list[str] = []

    def _fail_first(entry: BootstrapEntry, **_kwargs: object) -> bool:
        seen.append(entry.name)
        return entry.name != entries[0]

    monkeypatch.setattr(infra, "render_and_apply", _fail_first)
    assert infra._apply_cluster_bootstrap("/kc", env="staging", dry_run=False) is False
    assert seen == entries[:1]


def test_an_entry_scoped_to_one_environment_is_applied_only_there(monkeypatch: pytest.MonkeyPatch) -> None:
    """`envs` is read by the loop: the Sealed Secrets controller must not reach a cluster that holds no key for it."""
    from toolkit.cli import infra

    applied: dict[str, list[str]] = {}
    for env in ("staging", "prod"):
        seen: list[str] = []

        def _record(entry: BootstrapEntry, _seen: list[str] = seen, **_kw: object) -> bool:
            _seen.append(entry.name)
            return True

        monkeypatch.setattr(infra, "render_and_apply", _record)
        assert infra._apply_cluster_bootstrap("/kc", env=env, dry_run=False) is True
        applied[env] = seen

    assert "sealed-secrets" in applied["staging"]
    assert "sealed-secrets" not in applied["prod"]
    everywhere = [e.name for e in _load_cluster_bootstrap() if e.envs is None]
    assert everywhere, "an unscoped entry must still reach every environment"
    assert all(name in applied["prod"] for name in everywhere)
    assert all(name in applied["staging"] for name in everywhere)


def test_the_sealed_secrets_controller_is_declared_for_staging_only() -> None:
    assert next(e for e in _load_cluster_bootstrap() if e.name == "sealed-secrets").envs == ("staging",)


def test_envs_parse_and_default_to_every_environment() -> None:
    base = {"name": "x", "namespace": "n", "manifest": "m.yaml"}
    assert BootstrapEntry.from_dict(base).envs is None
    assert BootstrapEntry.from_dict({**base, "envs": ["staging"]}).envs == ("staging",)


def test_an_empty_envs_list_is_refused_not_read_as_never_applied() -> None:
    """`envs: []` would silently install nowhere; a typo must fail where it is written."""
    with pytest.raises(ValueError, match="envs"):
        BootstrapEntry.from_dict({"name": "x", "namespace": "n", "manifest": "m.yaml", "envs": []})


@pytest.mark.parametrize("command", ["bootstrap", "deploy", "dry-run"])
def test_every_caller_of_the_loop_passes_its_own_environment(mocker: pytest.MockerFixture, command: str) -> None:
    """The three commands that run the loop name their env, or `envs` would silently scope nothing."""
    from types import SimpleNamespace

    from toolkit.cli import infra

    mocker.patch.object(infra, "validate_environment_config", return_value=SimpleNamespace())
    mocker.patch.object(infra, "confirm_dangerous_operation")
    mocker.patch.object(infra, "_get_kubeconfig", return_value="/kc")
    mocker.patch.object(infra, "_kubectl_cmd", return_value="kubectl")
    mocker.patch.object(infra, "_generate_k8s_manifests", return_value=True)
    mocker.patch.object(infra.Path, "exists", return_value=True)
    mocker.patch.object(infra.command, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    loop = mocker.patch.object(infra, "_apply_cluster_bootstrap", return_value=False)  # stop right after it

    call = {
        "bootstrap": lambda: infra.k8s_bootstrap(env="prod", dry_run=True),
        "deploy": lambda: infra.k8s_deploy(env="prod", skip_generate=True),
        "dry-run": lambda: infra.k8s_dry_run(env="prod"),
    }[command]
    with pytest.raises(typer.Exit):
        call()

    assert loop.call_args.kwargs["env"] == "prod"
