"""`verify-sealed-secrets` compares digests and prints `match` or `mismatch`, nothing else (RES-HOST-001 A6, AC8).

The probe is a `SealedSecret` sealed offline against the SOPS certificate. If the
controller decrypts it, the Secret it creates holds a value whose sha256 equals
the digest committed beside the ciphertext: that is the proof the controller runs
the operator's key. The check reads a decrypted credential, so what it may print
is part of what it is. The canary below is a value that must never reach a
terminal, a log or a CI transcript.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
import yaml

from toolkit.cli import infra
from toolkit.features import sealed_secrets_probe as probe_mod
from toolkit.features.sealed_secrets_probe import DIGEST_ANNOTATION, Probe, ProbeError, load_probe

CANARY = "canary-plaintext-0f3a9c"
CANARY_SHA = hashlib.sha256(CANARY.encode()).hexdigest()


def _manifest(path: Path, **override: object) -> Path:
    doc = {
        "apiVersion": "bitnami.com/v1alpha1",
        "kind": "SealedSecret",
        "metadata": {
            "name": "sealed-secrets-probe",
            "namespace": "kube-system",
            "annotations": {DIGEST_ANNOTATION: CANARY_SHA},
        },
        "spec": {"encryptedData": {"probe": "AgBy8..."}},
    }
    for dotted, value in override.items():
        node = doc
        *parents, leaf = dotted.split("__")
        for parent in parents:
            node = node[parent]  # type: ignore[assignment]
        node[leaf] = value  # type: ignore[index]
    path.write_text(yaml.safe_dump(doc), encoding="utf-8", newline="\n")
    return path


def _secret(value: str | None, *, returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    """What `kubectl get secret -o json --ignore-not-found` returns: nothing at all when the Secret is absent."""
    out = "" if value is None else json.dumps({"data": {"probe": base64.b64encode(value.encode()).decode()}})
    return SimpleNamespace(returncode=returncode, stdout=out, stderr=stderr)


class TestLoadProbe:
    def test_reads_the_identity_and_the_expected_digest(self, tmp_path: Path) -> None:
        assert load_probe(_manifest(tmp_path / "p.yaml")) == Probe(
            "kube-system", "sealed-secrets-probe", "probe", CANARY_SHA
        )

    def test_a_missing_file_says_the_probe_is_not_committed_yet(self, tmp_path: Path) -> None:
        with pytest.raises(ProbeError, match="not committed"):
            load_probe(tmp_path / "absent.yaml")

    @pytest.mark.parametrize(
        "override",
        [
            {"kind": "Secret"},
            {"metadata__annotations": {}},
            {"metadata__annotations": {DIGEST_ANNOTATION: "abc"}},
            {"metadata__annotations": {DIGEST_ANNOTATION: CANARY_SHA.upper()}},
            {"spec__encryptedData": {}},
            {"spec__encryptedData": {"a": "x", "b": "y"}},
        ],
        ids=["wrong-kind", "no-digest", "short-digest", "uppercase-digest", "no-ciphertext", "two-values"],
    )
    def test_refuses_a_probe_it_cannot_check_exactly(self, tmp_path: Path, override: dict) -> None:
        with pytest.raises(ProbeError):
            load_probe(_manifest(tmp_path / "p.yaml", **override))


class TestVerify:
    PROBE = Probe("kube-system", "sealed-secrets-probe", "probe", CANARY_SHA)

    def test_the_digest_of_the_decrypted_value_matches(self) -> None:
        assert probe_mod.verify(self.PROBE, "/kc", run=lambda *a, **k: _secret(CANARY)) is True

    def test_another_value_is_a_mismatch(self) -> None:
        assert probe_mod.verify(self.PROBE, "/kc", run=lambda *a, **k: _secret("the controller's own key")) is False

    def test_a_secret_the_controller_never_made_is_a_mismatch(self) -> None:
        assert probe_mod.verify(self.PROBE, "/kc", run=lambda *a, **k: _secret(None)) is False

    def test_kubectl_failing_is_an_error_not_a_mismatch(self) -> None:
        """A cluster that cannot be read says nothing about the key; `mismatch` would misdirect the operator."""
        with pytest.raises(ProbeError, match="Forbidden"):
            probe_mod.verify(self.PROBE, "/kc", run=lambda *a, **k: _secret(None, returncode=1, stderr="Forbidden"))

    def test_asks_the_env_cluster_for_the_probes_secret(self) -> None:
        seen: list[list[str]] = []

        def run(cmd: list[str], **_: object) -> SimpleNamespace:
            seen.append(cmd)
            return _secret(CANARY)

        probe_mod.verify(self.PROBE, "/kc-staging", run=run)

        cmd = seen[0]
        assert cmd[cmd.index("--kubeconfig") + 1] == "/kc-staging"
        assert cmd[cmd.index("-n") + 1] == "kube-system"
        assert "sealed-secrets-probe" in cmd
        # A Secret the controller never made is a verdict (`mismatch`), not a kubectl NotFound error.
        assert "--ignore-not-found" in cmd


class TestCommand:
    @pytest.fixture
    def committed(self, tmp_path: Path, mocker: pytest.MonkeyPatch) -> Path:
        path = _manifest(tmp_path / "probe.yaml")
        mocker.patch.object(infra, "PROBE_MANIFEST", path)
        mocker.patch.object(infra, "_get_kubeconfig", return_value="/kc")
        return path

    def _run(self, mocker: pytest.MonkeyPatch, result: SimpleNamespace) -> None:
        mocker.patch.object(subprocess, "run", return_value=result)

    def test_match_prints_match_and_nothing_else(self, committed, mocker, capsys) -> None:
        self._run(mocker, _secret(CANARY))

        assert infra.k8s_verify_sealed_secrets(env="staging") is None

        captured = capsys.readouterr()
        assert captured.out == "match\n"
        assert CANARY not in captured.out + captured.err

    def test_mismatch_prints_mismatch_exits_1_and_leaks_neither_value(self, committed, mocker, capsys) -> None:
        wrong = "a value the controller made itself"
        self._run(mocker, _secret(wrong))

        with pytest.raises(typer.Exit) as exc:
            infra.k8s_verify_sealed_secrets(env="staging")

        captured = capsys.readouterr()
        assert exc.value.exit_code == 1
        assert captured.out == "mismatch\n"
        assert wrong not in captured.out + captured.err
        assert hashlib.sha256(wrong.encode()).hexdigest() not in captured.out + captured.err

    def test_a_cluster_error_exits_2_without_printing_a_verdict(self, committed, mocker, capsys) -> None:
        self._run(mocker, _secret(None, returncode=1, stderr="connection refused"))

        with pytest.raises(typer.Exit) as exc:
            infra.k8s_verify_sealed_secrets(env="staging")

        assert exc.value.exit_code == 2
        assert capsys.readouterr().out not in {"match\n", "mismatch\n"}
