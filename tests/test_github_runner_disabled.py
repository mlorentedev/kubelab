"""#3080 -- the GitHub runner on bee is declared off, and off means absent.

The container rendered unconditionally while nothing used it (`RUNNER_DOCKER` is
hosted since the ADR-030 amendment) and no runner was registered. On 2026-11-06 it
was crash-looping: its self-update deleted `/actions-runner/bin`, a restart reuses
the container's layer, so the listener never came back. Every provision then failed
its running check and reported `Start services` changed, so no run of the role could
be idempotent.

`enabled` governs presence AND absence, as `gitea_runner.enabled` does: Ansible is
additive, so a service deleted from the template keeps running as a compose orphan
(`up -d` never removes one). The role therefore removes the container itself.
"""

from __future__ import annotations

import pathlib

import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env
from tests.test_gitea_actions_runner import _ssot, _template_vars

REPO = pathlib.Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
TASKS = ROLE / "tasks/main.yml"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-bee.yml"
SERVICE = "github-runner"


def _declaration() -> dict:
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))
    return common["apps"]["services"]["automation"]["github_runner"]


def _services(enabled: bool) -> dict:
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    rendered = env.get_template("compose.yml.j2").render(**{**_template_vars(_ssot()), "runner_enabled": enabled})
    return yaml.safe_load(rendered)["services"]


def _tasks() -> list[dict]:
    return yaml.safe_load(TASKS.read_text(encoding="utf-8"))


def _task(name: str) -> dict:
    matches = [t for t in _tasks() if t.get("name") == name]
    assert len(matches) == 1, f"expected one task named {name!r}, found {len(matches)}"
    return matches[0]


def test_the_runner_is_declared_off() -> None:
    assert _declaration()["enabled"] is False


def test_the_playbook_passes_the_flag_from_the_declaration() -> None:
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert 'runner_enabled: "{{ config.apps.services.automation.github_runner.enabled }}"' in text


def test_off_renders_no_runner_service() -> None:
    assert SERVICE not in _services(enabled=False)


def test_on_still_renders_the_runner_service() -> None:
    """The branch is a switch, not a deletion: re-enabling is #2064's decision."""
    assert SERVICE in _services(enabled=True)


def test_the_role_removes_the_container_when_off() -> None:
    task = _task("Remove the GitHub runner container when it is not declared")
    assert task["command"] == "docker rm -f {{ runner_container_name }}"
    assert task["when"] == "not (runner_enabled | bool)"
    # Idempotent: an absent container is the converged state, not a change or a failure.
    assert task["changed_when"] == "_github_runner_rm.stdout | length > 0"
    assert "No such container" in task["failed_when"]


def test_a_removal_is_judged_by_what_docker_printed_not_its_exit_code() -> None:
    """`docker rm -f` exits 0 for a container that does not exist (Docker 29.9.2,
    measured on bee 2026-11-06), so `changed_when: rc == 0` reports a change on
    every run once the container is gone. Both absence tasks share the trap."""
    for name, var in (
        ("Remove the GitHub runner container when it is not declared", "_github_runner_rm"),
        ("Remove the act_runner container when it is not declared", "_act_runner_rm"),
    ):
        assert _task(name)["changed_when"] == f"{var}.stdout | length > 0", name


def test_the_running_check_only_applies_when_on() -> None:
    assert _task("Verify GitHub Runner container is running")["when"] == "runner_enabled | bool"


def test_the_image_is_only_pulled_when_on() -> None:
    text = TASKS.read_text(encoding="utf-8")
    assert "([runner_image] if runner_enabled | bool else [])" in text


def test_the_container_name_comes_from_the_declaration() -> None:
    """The removal, the probe and the render must all name the declared container.
    A literal in one of them means a rename in `common.yaml` leaves that one
    addressing a container that no longer exists, and `docker rm -f` on a missing
    name reports nothing (lesson-715)."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert 'runner_container_name: "{{ config.apps.services.automation.github_runner.name }}"' in text
    assert _task("Verify GitHub Runner container is running")["command"].endswith("{{ runner_container_name }}")
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined)
    rendered = env.get_template("compose.yml.j2").render(
        **{**_template_vars(_ssot()), "runner_enabled": True, "runner_container_name": "renamed-runner"}
    )
    assert yaml.safe_load(rendered)["services"][SERVICE]["container_name"] == "renamed-runner"
    assert _declaration()["name"] == SERVICE
