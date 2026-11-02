"""DATA-007: the generated migration Job carries the committed migrations and no secret."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = REPO_ROOT / "apps" / "api" / "migrations"


def _rendered(env: str) -> dict[str, dict]:
    path = REPO_ROOT / "infra" / "k8s" / "overlays" / env / "generated" / "migrations.yaml"
    docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    return {d["kind"]: d for d in docs}


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_configmap_holds_every_migration_file_verbatim(env: str) -> None:
    data = _rendered(env)["ConfigMap"]["data"]
    assert set(data) == {p.name for p in MIGRATIONS.iterdir()}
    for path in MIGRATIONS.iterdir():
        assert data[path.name].strip() == path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_a_new_migration_gets_a_new_job(env: str) -> None:
    digest = hashlib.sha256()
    for path in sorted(MIGRATIONS.iterdir()):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    suffix = digest.hexdigest()[:10]

    docs = _rendered(env)
    assert docs["Job"]["metadata"]["name"] == f"api-migrate-{suffix}"
    assert docs["ConfigMap"]["metadata"]["name"] == f"api-migrations-{suffix}"


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_job_connects_as_the_tenant_with_the_password_from_the_secret(env: str) -> None:
    job = _rendered(env)["Job"]["spec"]["template"]["spec"]
    container = job["containers"][0]
    url = container["args"][container["args"].index("--url") + 1]
    assert url.startswith("postgres://api:$(POSTGRES_TENANT_PASSWORD)@postgres:5432/api")
    assert job["restartPolicy"] == "Never"
    ref = container["env"][0]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "api-secrets", "key": "POSTGRES_TENANT_PASSWORD"}
