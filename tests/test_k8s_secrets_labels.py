"""A `SecretMapping` may carry labels, and every mapping without them renders as before.

The Sealed Secrets controller adopts only a key Secret labelled
`sealedsecrets.bitnami.com/sealed-secrets-key=active`, and `apply_secrets` is the
only writer of that Secret (RES-HOST-001 A3, F7). The field must not change what
the existing mappings send to the cluster: `kubectl apply` replaces the whole
object, so a stray `labels: {}` would be a diff on every Secret in both clusters.
"""

from __future__ import annotations

import pytest
import yaml

from toolkit.features import k8s_secrets as ks
from toolkit.features.k8s_secrets import (
    SECRET_DEFINITIONS,
    SecretMapping,
    _apply_single_secret,
    _render_secret_manifest,
)

# What the renderer produced before `labels` existed, captured on 2026-11-14.
GOLDEN_OPAQUE = (
    "apiVersion: v1\nkind: Secret\nmetadata:\n  name: crowdsec-bouncer-traefik\n  namespace: kube-system\n"
    "type: Opaque\ndata:\n  api-key: YWJj\n"
)
GOLDEN_PULL = (
    "apiVersion: v1\nkind: Secret\nmetadata:\n  name: pull-x\n  namespace: kubelab\n"
    "type: kubernetes.io/dockerconfigjson\ndata:\n  .dockerconfigjson: e30=\n"
)


def test_a_mapping_without_labels_renders_byte_identically() -> None:
    assert _render_secret_manifest("crowdsec-bouncer-traefik", "kube-system", {"api-key": "abc"}) == GOLDEN_OPAQUE
    assert (
        _render_secret_manifest("pull-x", "kubelab", {".dockerconfigjson": "{}"}, "kubernetes.io/dockerconfigjson")
        == GOLDEN_PULL
    )


def test_empty_labels_render_no_labels_key() -> None:
    assert _render_secret_manifest("crowdsec-bouncer-traefik", "kube-system", {"api-key": "abc"}, labels={}) == (
        GOLDEN_OPAQUE
    )


def test_labels_render_in_the_metadata() -> None:
    out = _render_secret_manifest("k", "kube-system", {"a": "b"}, "kubernetes.io/tls", {"x.io/y": "active"})
    assert yaml.safe_load(out)["metadata"] == {"name": "k", "namespace": "kube-system", "labels": {"x.io/y": "active"}}


def test_apply_sends_the_labels_of_the_mapping(mocker: pytest.MonkeyPatch) -> None:
    run = mocker.patch.object(ks.subprocess, "run")
    run.return_value = mocker.Mock(stdout="secret/k created", stderr="", returncode=0)
    mapping = SecretMapping(name="k", keys={"a": "A_ENV"}, labels={"x.io/y": "active"})

    assert _apply_single_secret(mapping, {"A_ENV": "v"}, {}, dry_run=False, env="staging") is True

    sent = yaml.safe_load(run.call_args.kwargs["input"])
    assert sent["metadata"]["labels"] == {"x.io/y": "active"}


@pytest.mark.parametrize("mapping", SECRET_DEFINITIONS, ids=lambda m: m.name)
def test_a_mapping_that_declares_no_labels_sends_none(mapping: SecretMapping, mocker: pytest.MonkeyPatch) -> None:
    """The proof for every mapping that existed before the field: its metadata is name and namespace only."""
    if mapping.labels:
        pytest.skip("declares labels on purpose; see test_sealed_secrets_bootstrap.py")
    run = mocker.patch.object(ks.subprocess, "run")
    run.return_value = mocker.Mock(stdout="secret/x configured", stderr="", returncode=0)
    env_vars = {env: "v" for env in {*mapping.keys.values(), *mapping.optional_keys.values()}}

    assert _apply_single_secret(mapping, env_vars, mapping.literals or {"k": "v"}, dry_run=True, env="staging")

    sent = yaml.safe_load(run.call_args.kwargs["input"])
    assert set(sent["metadata"]) == {"name", "namespace"}
