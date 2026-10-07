"""ace2's backup sources name what the agent_stack role creates (spec AI-009 AC7).

`backup.sources` cannot reference the role's variables, so the two are compared
here: a renamed volume or a moved data directory fails this test instead of
leaving the backup capturing a path that no longer holds anything.
"""

from __future__ import annotations

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from tests.test_agent_stack_role import ROLE, _common, _render, _resolved


def _sources() -> dict:
    return _common()["backup"]["sources"]["ace2"]


def test_open_webui_is_captured_from_the_volume_its_compose_mounts() -> None:
    volumes = yaml.safe_load(_render("compose-webui.yml.j2"))["volumes"]
    assert [v["name"] for v in volumes.values()] == [_sources()["open_webui"]["volume"]]


def test_hermes_is_captured_from_its_home_and_not_from_its_env_file() -> None:
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    context = _resolved(env)
    path = _sources()["hermes"]["path"]
    assert path == context["agent_stack_hermes_home"]
    # The rendered secrets are rebuilt from SOPS; they stay out of the snapshot.
    for secret in (context["agent_stack_hermes_env"], context["agent_stack_hermes_ts_env"]):
        assert not secret.startswith(path + "/"), secret


def test_ace2_ships_to_its_own_bucket_from_its_first_snapshot() -> None:
    """Born on the per-node model: it never had a copy in the shared bucket to migrate."""
    assert "ace2" in _common()["backup"]["r2"]["own_bucket_nodes"]
