"""`DockerService.validate_volume_mounts`: which compose volume sources it checks, and when it gives up.

It gates `up` for the Compose stacks, so its fail-open cases are behaviour, not accident:
a compose file it cannot render or parse must not block a deploy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.docker_service import DockerService


def _service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, stdout: str = "", returncode: int = 0
) -> DockerService:
    settings = type("S", (), {"project_root": tmp_path})()
    svc = DockerService(settings)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_get_execution_env", lambda env: {})
    monkeypatch.setattr(svc, "_get_compose_cmd", lambda d, env, action: ["docker", "compose", action])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=stdout, stderr="boom"),
    )
    return svc


def _compose(*volumes: Any) -> str:
    return yaml.safe_dump({"services": {"app": {"volumes": list(volumes)}}})


def test_every_existing_bind_source_passes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "conf").mkdir()
    (tmp_path / "abs").mkdir()
    stdout = _compose(
        {"type": "bind", "source": str(tmp_path / "abs"), "target": "/a"},
        "./conf:/etc/conf:ro",
        {"type": "volume", "source": "data", "target": "/data"},
        "named:/data",
        "/only-a-target",
    )
    assert _service(monkeypatch, tmp_path, stdout=stdout).validate_volume_mounts(tmp_path, "dev") is True


@pytest.mark.parametrize(
    "volume",
    [
        {"type": "bind", "source": "/definitely/not/here", "target": "/a"},
        "./missing:/m",
        "../missing-too:/m",
    ],
)
def test_a_missing_bind_source_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, volume: Any) -> None:
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    assert _service(monkeypatch, tmp_path, stdout=_compose(volume)).validate_volume_mounts(service_dir, "dev") is False


def test_a_relative_source_resolves_against_the_service_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service_dir = tmp_path / "svc"
    (service_dir / "conf").mkdir(parents=True)
    (tmp_path / "conf").mkdir()
    stdout = _compose("./conf:/c")
    assert _service(monkeypatch, tmp_path, stdout=stdout).validate_volume_mounts(service_dir, "dev") is True
    assert _service(monkeypatch, tmp_path, stdout=stdout).validate_volume_mounts(tmp_path / "other", "dev") is False


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [("", 1), ("services: [unclosed\n", 0), ("services: 7\n", 0)],
)
def test_it_fails_open_when_the_config_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdout: str, returncode: int
) -> None:
    svc = _service(monkeypatch, tmp_path, stdout=stdout, returncode=returncode)
    assert svc.validate_volume_mounts(tmp_path, "dev") is True


def test_an_unreadable_source_counts_as_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def denied(self: Path) -> bool:
        raise PermissionError

    stdout = _compose("/root/secret:/s")
    svc = _service(monkeypatch, tmp_path, stdout=stdout)
    monkeypatch.setattr(Path, "exists", denied)
    assert svc.validate_volume_mounts(tmp_path, "dev") is True
