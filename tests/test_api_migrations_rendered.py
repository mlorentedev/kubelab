"""DATA-007: the generated migration Job carries the committed migrations and no secret."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.generator_k8s import K8sGenerator

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
        assert data[path.name] == path.read_text(encoding="utf-8")


def _hash(root: Path, **overrides: str) -> str:
    generator = K8sGenerator.__new__(K8sGenerator)
    generator.project_root = root
    env_vars = {
        "INFRA_POSTGRES_ATLAS_IMAGE": "atlas:1",
        "APPS_PLATFORM_API_POSTGRES_TENANT": "api",
        "INFRA_POSTGRES_HOST": "postgres",
        "INFRA_POSTGRES_PORT": "5432",
    }
    return generator._build_migrations({**env_vars, **overrides})["hash"]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_job_and_configmap_share_one_hash(env: str) -> None:
    docs = _rendered(env)
    suffix = docs["Job"]["metadata"]["name"].removeprefix("api-migrate-")
    assert docs["ConfigMap"]["metadata"]["name"] == f"api-migrations-{suffix}"


def test_every_input_of_the_job_changes_its_name(tmp_path: Path) -> None:
    # A Job's spec is immutable: a change that keeps the name is a refused sync.
    (tmp_path / "apps" / "api" / "migrations").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "migrations" / "1.sql").write_text("a", encoding="utf-8")
    template = tmp_path / "infra" / "k8s" / "templates" / "migrations.yaml.j2"
    template.parent.mkdir(parents=True)
    template.write_text("t", encoding="utf-8")
    base = _hash(tmp_path)
    assert base != _hash(tmp_path, INFRA_POSTGRES_ATLAS_IMAGE="atlas:2")
    assert base != _hash(tmp_path, INFRA_POSTGRES_HOST="elsewhere")
    template.write_text("t2", encoding="utf-8")
    assert base != _hash(tmp_path)
    template.write_text("t", encoding="utf-8")
    (tmp_path / "apps" / "api" / "migrations" / "2.sql").write_text("b", encoding="utf-8")
    assert base != _hash(tmp_path)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_job_connects_as_the_tenant_with_the_password_from_the_secret(env: str) -> None:
    job = _rendered(env)["Job"]["spec"]["template"]["spec"]
    container = job["containers"][0]
    url = container["args"][container["args"].index("--url") + 1]
    common = yaml.safe_load((REPO_ROOT / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))
    tenant = common["apps"]["platform"]["api"]["postgres_tenant"]
    postgres = common["infra"]["postgres"]
    assert url.startswith(
        f"postgres://{tenant}:$(POSTGRES_TENANT_PASSWORD)@{postgres['host']}:{postgres['port']}/{tenant}"
    )
    assert job["restartPolicy"] == "Never"
    ref = container["env"][0]["valueFrom"]["secretKeyRef"]
    assert ref == {"name": "api-secrets", "key": "POSTGRES_TENANT_PASSWORD"}
