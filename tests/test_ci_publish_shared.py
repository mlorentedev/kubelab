"""`ci-publish.yml` builds through ci-workflows' shared `docker-publish.yml` (CI-010).

The shared workflow pushes each platform by digest, scans each with Trivy and
tags only when every scan passes. What stays here is what is kubelab's own: the
tag set, the image name, the labels and the notification. These tests pin the
parts a later edit could quietly widen: the pin, the secrets each caller hands
over, and the publish a Renovate branch forfeits (kubelab#3344).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github/workflows"
PUBLISH = WORKFLOWS / "ci-publish.yml"
SHARED = "mlorentedev/ci-workflows/.github/workflows/docker-publish.yml@"
NAMED_SECRETS = {"DOCKERHUB_USERNAME", "DOCKERHUB_TOKEN", "N8N_WEBHOOK_URL", "N8N_DEPLOY_TOKEN"}


def _load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(workflow: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True))


def _publish_calls() -> list[tuple[str, str, dict]]:
    calls = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for name, job in (_load(path).get("jobs") or {}).items():
            if job.get("uses") == "./.github/workflows/ci-publish.yml":
                calls.append((path.name, name, job))
    return calls


def test_the_build_is_the_shared_workflow_pinned_by_commit() -> None:
    job = _load(PUBLISH)["jobs"]["docker-build-push"]
    uses = job["uses"]
    assert uses.startswith(SHARED), uses
    assert re.fullmatch(r"[0-9a-f]{40}", uses.removeprefix(SHARED)), f"not pinned by commit: {uses}"
    assert job["secrets"] == {
        "REGISTRY_USERNAME": "${{ secrets.DOCKERHUB_USERNAME }}",
        "REGISTRY_TOKEN": "${{ secrets.DOCKERHUB_TOKEN }}",
    }
    # Every platform is scanned before a tag lands, and the SARIF stays per app.
    assert job["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert job["with"]["sarif-category"] == "trivy-${{ inputs.app }}"


def test_no_caller_inherits_secrets_into_the_publish() -> None:
    calls = _publish_calls()
    assert {(f, j) for f, j, _ in calls} == {
        ("ci-pipeline.yml", "call-publish"),
        ("release.yml", "publish-errors"),
        ("staging-deploy.yml", "build-api"),
        ("staging-deploy.yml", "build-console"),
    }
    declared = set(_on(_load(PUBLISH))["workflow_call"]["secrets"])
    assert declared == NAMED_SECRETS
    for file, name, job in calls:
        assert job.get("secrets") != "inherit", f"{file}:{name} inherits every secret"
        assert set(job["secrets"]) == NAMED_SECRETS, f"{file}:{name} passes {sorted(job['secrets'])}"


def test_a_renovate_branch_forfeits_the_publish() -> None:
    condition = _load(WORKFLOWS / "ci-pipeline.yml")["jobs"]["call-publish"]["if"]
    assert "||" not in condition, "a disjunction could route around the forfeit"
    conjuncts = [c.strip() for c in condition.split("&&")]
    assert "!startsWith(github.head_ref, 'renovate/')" in conjuncts
    assert "github.actor != 'dependabot[bot]'" in conjuncts


def _tags(tag: str, tmp_path: pathlib.Path) -> dict[str, str]:
    step = next(s for s in _load(PUBLISH)["jobs"]["tags"]["steps"] if s.get("id") == "docker_tags")
    out = tmp_path / "out"
    env = {
        **os.environ,
        "GITHUB_OUTPUT": str(out),
        "REGISTRY_PREFIX": "kubelab",
        "DOCKER_VERSION": tag,
        "OWNER": "mlorentedev",
        "APP": "api",
    }
    subprocess.run(["bash", "-e", "-c", step["run"]], env=env, check=True, capture_output=True)
    return dict(line.split("=", 1) for line in out.read_text().splitlines())


@pytest.mark.parametrize(
    ("tag", "tags", "tag_type"),
    [("sha-abc1234", "sha-abc1234", "sha"), ("1.4.0", "1.4.0,latest", "stable")],
)
def test_the_tag_set_is_decided_before_the_build(tmp_path: pathlib.Path, tag: str, tags: str, tag_type: str) -> None:
    got = _tags(tag, tmp_path)
    assert got["tags"] == tags
    assert got["tag_type"] == tag_type
    # The image the manifests pin, with its registry, and no tag in it.
    assert got["registry"] == "docker.io/mlorentedev/kubelab-api"
    assert got["full_image"] == f"docker.io/mlorentedev/kubelab-api:{tag}"
