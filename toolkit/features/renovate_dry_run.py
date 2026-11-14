"""Run Renovate's own engine against this repository, extract only (#3440).

`tests/test_renovate_image_coverage.py` checks Python copies of the regex
managers. A copy can match where Renovate does not, and a Renovate manager that
matches nothing reports success (lesson-691). This runs the real engine with
`--platform=local --dry-run=extract`: it reads the working tree, touches no
forge, opens nothing, and writes a JSON report of what each manager extracted.

The engine is the one the Gitea run uses: `renovate/engine.json` in
mlorentedev/ci-workflows at `ci.renovate.preset_tag`, so this module declares
no version of its own.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx
import yaml

ENGINE_URL = "https://raw.githubusercontent.com/mlorentedev/ci-workflows/{tag}/renovate/engine.json"
REPORT_NAME = "report.json"

# (manager, package file, dependency name, current value)
Extracted = set[tuple[str, str, str, str]]


def engine_image(common_yaml: Path) -> str:
    """The pinned engine image, read from ci-workflows at the declared preset tag."""
    common = yaml.safe_load(common_yaml.read_text(encoding="utf-8"))
    tag = common["ci"]["renovate"]["preset_tag"]
    response = httpx.get(ENGINE_URL.format(tag=tag), timeout=30, follow_redirects=True)
    response.raise_for_status()
    engine = response.json()
    return f"{engine['image']}:{engine['version']}"


def run_extract(repo: Path, out_dir: Path, image: str, *, timeout: int = 900) -> Path:
    """Run the engine over `repo` and return the path of the report it wrote.

    `out_dir` must be a directory the container can mount (on macOS, under $HOME).
    It is opened to every user because the engine runs as its own user, not as
    the caller.
    """
    out_dir.chmod(0o777)
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo.resolve()}:/repo:ro",
        "-v",
        f"{out_dir.resolve()}:/out",
        "-w",
        "/repo",
        "-e",
        "LOG_LEVEL=warn",
        "-e",
        "RENOVATE_REPORT_TYPE=file",
        "-e",
        f"RENOVATE_REPORT_PATH=/out/{REPORT_NAME}",
    ]
    if os.environ.get("GITHUB_COM_TOKEN"):
        # By name only: docker copies the value from this process's environment,
        # so it never appears in the command line.
        cmd += ["-e", "GITHUB_COM_TOKEN"]
    cmd += [image, "--platform=local", "--dry-run=extract"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False
    )
    report = out_dir / REPORT_NAME
    if result.returncode != 0 or not report.exists():
        raise RuntimeError(f"renovate exited {result.returncode} with no report:\n{result.stderr[-2000:]}")
    return report


def extracted(report: Path) -> Extracted:
    """Every dependency the report says a manager extracted."""
    repositories = json.loads(report.read_text(encoding="utf-8"))["repositories"]
    found: Extracted = set()
    for repository in repositories.values():
        for manager, files in repository["packageFiles"].items():
            for package_file in files:
                for dep in package_file["deps"]:
                    found.add(
                        (
                            manager,
                            package_file["packageFile"],
                            dep.get("depName", ""),
                            dep.get("currentValue", ""),
                        )
                    )
    return found
