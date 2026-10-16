"""Homepage reads no Secret, and the one it used to read is retired (#1761).

`homepage-secrets` mapped three keys to SOPS paths that never existed, so `apply-secrets`
wrote a Secret of empty values and reported success. Two widgets put two of those values
in an `Authorization` header: the GitHub one sent `Bearer ` and was answered 401 by an API
that answers its public endpoint 200 without a header. Nothing failed loudly, which is why
the Secret outlived every review. These tests pin the state after removing it.
"""

from __future__ import annotations

from pathlib import Path

from toolkit.features import k8s_secrets

K8S = Path(__file__).resolve().parents[1] / "infra" / "k8s"


def _text_files() -> list[Path]:
    return [p for p in K8S.rglob("*") if p.is_file() and p.suffix in {".yaml", ".yml", ".j2", ".json"}]


def test_no_homepage_variable_is_referenced_anywhere_in_the_manifests_or_templates() -> None:
    offenders = [str(p.relative_to(K8S)) for p in _text_files() if "HOMEPAGE_VAR_" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"a HOMEPAGE_VAR_* reference needs a Secret that resolves, and none exists: {offenders}"


def test_no_manifest_mounts_the_retired_secret() -> None:
    offenders = [str(p.relative_to(K8S)) for p in _text_files() if "homepage-secrets" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"a pod referencing a Secret that apply-secrets deletes does not start: {offenders}"


def test_the_secret_is_no_longer_rendered_and_is_deleted_on_every_apply() -> None:
    assert "homepage-secrets" not in {m.name for m in k8s_secrets.SECRET_DEFINITIONS}
    assert ("kubelab", "homepage-secrets") in k8s_secrets.RETIRED_SECRETS
