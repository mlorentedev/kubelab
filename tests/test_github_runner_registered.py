"""#3080 AC3 -- a GitHub runner declared enabled must be registered, or the run fails.

The container on bee rendered and ran while GitHub listed no runner, and nothing
noticed (the PAT in #1248 is the likely cause). A running container is a local
fact; registration is GitHub's, so the role asks GitHub. These tests evaluate the
role's own expressions with the Ansible filters they use, against the answers
GitHub can give: listed, not listed, and the token refused.
"""

from __future__ import annotations

import pathlib
from urllib.parse import urlsplit

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = pathlib.Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/beelink_services"
QUERY = "Verify GitHub lists the declared runner as registered"
FAIL = "Fail when GitHub does not list the declared runner"


def _task(name: str) -> dict:
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))
    matches = [t for t in tasks if t.get("name") == name]
    assert len(matches) == 1, f"expected one task named {name!r}, found {len(matches)}"
    return matches[0]


def _env():  # type: ignore[no-untyped-def]
    env = ansible_env(str(ROLE / "templates"))
    env.filters["urlsplit"] = lambda url, part: getattr(urlsplit(url), part)
    return env


def _expr(text: str) -> str:
    """A bare Ansible condition, made renderable as a Jinja expression."""
    return "{{ " + text.strip() + " }}"


def _fails(registration: dict, name: str = "kubelab-bee") -> bool:
    condition = _task(FAIL)["when"][1]
    rendered = _env().from_string(_expr(condition)).render(_runner_registration=registration, runner_name=name)
    return rendered == "True"


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def test_both_tasks_only_run_when_the_runner_is_declared() -> None:
    assert _task(QUERY)["when"] == "runner_enabled | bool"
    assert _task(FAIL)["when"][0] == "runner_enabled | bool"


def test_the_query_never_logs_the_token_and_leaves_failing_to_the_next_task() -> None:
    task = _task(QUERY)
    assert task["no_log"] is True
    assert task["ignore_errors"] is True
    assert task["changed_when"] is False
    assert task["check_mode"] is False
    assert "{{ runner_access_token }}" in task["uri"]["headers"]["Authorization"]


def test_the_query_asks_for_the_repository_the_runner_is_declared_for() -> None:
    url = _env().from_string(_task(QUERY)["uri"]["url"]).render(runner_repo_url="https://github.com/mlorentedev/kubelab")
    assert url == "https://api.github.com/repos/mlorentedev/kubelab/actions/runners?per_page=100"


@pytest.mark.parametrize(
    ("registration", "fails"),
    [
        pytest.param({"status": 200, "json": {"runners": [{"name": "kubelab-bee"}]}}, False, id="registered"),
        pytest.param({"status": 200, "json": {"runners": []}}, True, id="none registered"),
        pytest.param({"status": 200, "json": {"runners": [{"name": "other"}]}}, True, id="another runner only"),
        pytest.param({"status": 401}, True, id="token refused"),
    ],
)
def test_the_run_fails_unless_github_lists_the_declared_name(registration: dict, fails: bool) -> None:
    assert _fails(registration) is fails


def test_the_failure_names_an_expired_token_when_github_refuses_it() -> None:
    msg = _env().from_string(_task(FAIL)["fail"]["msg"]).render(_runner_registration={"status": 401}, runner_name="x")
    assert "HTTP 401" in msg and "#1248" in msg


def test_the_compose_file_and_the_check_name_the_same_runner() -> None:
    """A literal in one of them would let the check look for a name nothing registers."""
    assert _defaults()["runner_name"] == "kubelab-bee"
    compose = (ROLE / "templates/compose.yml.j2").read_text(encoding="utf-8")
    assert 'RUNNER_NAME: "{{ runner_name }}"' in compose
    assert "kubelab-bee" not in compose
