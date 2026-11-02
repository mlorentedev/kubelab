"""node_maintenance has two implementations of its Docker cleanup — the
Ansible tasks `make maintain` runs, and the shell script the weekly timer
runs — and nothing enforces that they agree. ANSIBLE-046 (#1456) added a
stopped-container prune and an orphaned-buildx-builder warning to close a gap
(months-old `buildx_buildkit_builder-<uuid>` containers, invisible to
`docker buildx ls`, that the existing `docker builder prune` never reached).
This guards that the two implementations still say the same thing.
"""

from __future__ import annotations

import pathlib
import re

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/node_maintenance"


def _tasks() -> str:
    return (ROLE / "tasks/main.yml").read_text(encoding="utf-8")


def _render_script() -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = lambda v: str(v).lower() in ("true", "yes", "1")
    tpl = (ROLE / "templates/kubelab-maintenance.sh.j2").read_text(encoding="utf-8")
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    return env.from_string(tpl).render({**defaults, "ansible_managed": "am", "inventory_hostname": "kubelab-vps"})


KEEP_STACKS = '--filter "label!=com.docker.compose.project"'


def _container_prunes(text: str) -> list[str]:
    """Each `docker container prune` command line, not the text of its warning."""
    return re.findall(r"docker container prune -[^\n]*", text)


def test_both_implementations_prune_stopped_containers() -> None:
    assert "docker container prune -f" in _tasks()
    assert "docker container prune -f" in _render_script()


@pytest.mark.parametrize("source", ["tasks", "script"])
def test_a_stopped_stack_keeps_its_container_and_so_its_image(source: str) -> None:
    """`image prune -a` spares an image a container still references, stopped or not.
    A stack's units stop with `compose stop`, so their containers outlive a stop,
    and only the container prune could take them, and the image with them. ace2 lost
    its Open WebUI image that way (#2703)."""
    text = _tasks() if source == "tasks" else _render_script()
    prunes = _container_prunes(text)
    assert prunes, f"no container prune found in the {source}"
    for prune in prunes:
        assert KEEP_STACKS in prune, f"{source}: {prune!r} would remove a stopped compose stack"


def test_both_implementations_check_for_orphaned_buildx_builders() -> None:
    assert "buildx_buildkit_builder-" in _tasks()
    assert "buildx_buildkit_builder-" in _render_script()
