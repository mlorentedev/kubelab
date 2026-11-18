"""The Sealed Secrets controller on staging adopts the operator's key, not one it mints (RES-HOST-001 A1-A5).

The controller reads, from its own namespace, a Secret labelled
`sealedsecrets.bitnami.com/sealed-secrets-key=active`. When none exists at its
first start it generates one, and every `SealedSecret` sealed offline against the
SOPS-held certificate is then undecryptable: nothing fails at apply time, the
failure is a Secret that never appears. So the properties here are the ones that
decide which key the controller ends up with: the image it runs, the flag that
stops it minting a second key, the Secret that carries the first one, and the
order the two are applied in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from toolkit.cli.infra import _load_cluster_bootstrap
from toolkit.features.k8s_render import BootstrapEntry
from toolkit.features.k8s_secrets import SECRET_DEFINITIONS, SecretMapping
from toolkit.features.secrets_manager import SECRET_CATALOG

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_KEY_LABEL = {"sealedsecrets.bitnami.com/sealed-secrets-key": "active"}
KEY_MAPPING = "sealed-secrets-key"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _entry() -> BootstrapEntry:
    return next(e for e in _load_cluster_bootstrap() if e.name == "sealed-secrets")


def _docs(entry: BootstrapEntry) -> list[dict]:
    return [d for d in yaml.safe_load_all((ROOT / entry.manifest).read_text(encoding="utf-8")) if d]


def _controller(entry: BootstrapEntry) -> dict:
    deployments = [d for d in _docs(entry) if d["kind"] == "Deployment"]
    assert len(deployments) == 1, "the controller is one Deployment"
    (container,) = deployments[0]["spec"]["template"]["spec"]["containers"]
    return container


def _mapping() -> SecretMapping:
    return next(m for m in SECRET_DEFINITIONS if m.name == KEY_MAPPING)


def test_the_bootstrap_layer_installs_the_controller_in_its_namespace() -> None:
    entry = _entry()
    assert (ROOT / entry.manifest).is_file()
    assert entry.optional is False, "a skipped controller leaves every SealedSecret unread without a failure"
    # Every namespaced object in the vendored manifest is in the entry's namespace, which is
    # where the controller looks for its key.
    namespaces = {d["metadata"].get("namespace") for d in _docs(entry) if d["kind"] in {"Deployment", "Service"}}
    assert namespaces == {entry.namespace}


def test_the_controller_image_is_pinned_by_digest() -> None:
    image = _controller(_entry())["image"]
    assert DIGEST.search(image), f"{image} is a moving tag: a registry push changes what the cluster runs"


def test_the_image_tag_is_the_entry_version() -> None:
    """The digest alone does not say which release this is; the tag beside it must agree with the pin."""
    entry = _entry()
    assert entry.version is not None
    assert f":{entry.version.removeprefix('v')}@" in _controller(entry)["image"]


def test_the_controller_never_renews_its_key() -> None:
    """Renewal would mint a second active key that nothing sealed against is held in SOPS."""
    assert "--key-renew-period=0" in _controller(_entry())["args"]


def test_the_key_secret_carries_the_active_label_in_the_controllers_namespace() -> None:
    mapping = _mapping()
    assert mapping.labels == ACTIVE_KEY_LABEL
    assert mapping.namespace == _entry().namespace
    assert mapping.secret_type == "kubernetes.io/tls"
    assert set(mapping.keys) == {"tls.crt", "tls.key"}


def test_the_key_secret_is_scoped_to_the_environment_that_runs_the_controller() -> None:
    """An unscoped mapping would be demanded of prod, where no value exists, and fail every apply there."""
    assert _mapping().envs == ("staging",)


@pytest.mark.parametrize("k8s_key", ["tls.crt", "tls.key"])
def test_each_half_of_the_key_pair_is_a_catalogued_sops_secret(k8s_key: str) -> None:
    mapping = _mapping()
    env_var = mapping.keys[k8s_key]
    specs = [s for s in SECRET_CATALOG if s.key_path.upper().replace(".", "_") == env_var]
    assert len(specs) == 1, f"{env_var} has no single catalog entry"
    assert specs[0].envs == mapping.envs


def test_no_private_key_is_committed_beside_the_controller() -> None:
    """The owner generates the pair and sets it in SOPS; a PEM private key in this directory is a leak."""
    files = [p for p in (ROOT / _entry().manifest).parent.rglob("*") if p.is_file()]
    assert files, "the scan found nothing to read"
    assert [p.name for p in files if "PRIVATE KEY" in p.read_text(encoding="utf-8")] == []


def _rule(target: str) -> str:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:(?P<prereqs>[^\n]*)$", makefile, re.MULTILINE)
    assert match, f"{target} is no longer a Makefile target"
    return match.group("prereqs")


@pytest.mark.parametrize("target", ["bootstrap-k8s", "deploy-k8s"])
def test_secrets_are_applied_before_the_controller_starts(target: str) -> None:
    """Both targets reach `cluster_bootstrap`; on a fresh cluster the controller must find the key already there."""
    assert "apply-secrets" in _rule(target).split(), f"{target} no longer applies secrets before the controller"


def _spec(key_path: str):
    return next(s for s in SECRET_CATALOG if s.key_path == key_path)


def test_the_catalog_patterns_accept_each_half_and_refuse_a_swap() -> None:
    """`audit` holds a set value to its pattern: a key pasted into the certificate slot must not pass."""
    cert = "-----BEGIN CERTIFICATE-----\nMIIC\n-----END CERTIFICATE-----\n"
    # Assembled, so no file of this repo carries a PEM private-key marker (the secret scanners read tests too).
    private = "PRIVATE" + " KEY"
    keys = [f"-----BEGIN {private}-----\nMIIE\n-----END {private}-----\n"]
    keys.append(keys[0].replace(private, f"RSA {private}"))
    crt = re.compile(_spec("infra.sealed_secrets.tls_crt").value_pattern)
    key = re.compile(_spec("infra.sealed_secrets.tls_key").value_pattern)
    assert crt.fullmatch(cert)
    assert all(key.fullmatch(k) for k in keys)
    assert not crt.fullmatch(keys[0])
    assert not key.fullmatch(cert)


def test_the_bootstrap_layer_applies_the_probe_after_the_controller_where_it_runs() -> None:
    """A6: the committed probe reaches the cluster through bootstrap, never by hand.

    After the controller, because the SealedSecret kind is the controller's CRD; in the same
    environments, because elsewhere no key exists to unseal it.
    """
    from toolkit.features.sealed_secrets_probe import PROBE_MANIFEST

    entries = _load_cluster_bootstrap()
    names = [e.name for e in entries]
    probe = next(e for e in entries if e.manifest == PROBE_MANIFEST)

    assert names.index(probe.name) > names.index("sealed-secrets")
    assert probe.envs == _entry().envs
    assert probe.namespace == "kube-system"
