"""Render the edge's staging-zone consumers the way Ansible and the toolkit do (EDGE-001).

Each consumer is resolved from its own declaration, never from a list this module
picks: the `coredns` role's `staging_zones` default and the Headscale `split` loop
in `deploy-vps.yml` are evaluated as Jinja expressions, with Ansible's
`lookup('file', ...)` implemented over the repository. So whichever source a
consumer reads (the hand list in `common.yaml` before EDGE-001, the derived
`infra/config/products/edge.json` after), the render follows it, and comparing
the output with master's golden copy proves the switch moved nothing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jinja2
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/coredns"
PLAYBOOKS = REPO / "infra/ansible/playbooks"
VALUES = REPO / "infra/config/values"
COREDNS_CUSTOM = REPO / "infra/k8s/base/edge/coredns-custom.yaml"


def _lookup(kind: str, path: str) -> str:
    assert kind == "file", f"only lookup('file', ...) is implemented, got {kind!r}"
    return Path(os.path.normpath(path)).read_text(encoding="utf-8")


def _env() -> jinja2.Environment:
    # The template module's defaults: trim_blocks on, the source's trailing newline kept.
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    env.filters["from_json"] = json.loads
    env.globals["lookup"] = _lookup
    return env


def _common() -> dict[str, Any]:
    return yaml.safe_load((VALUES / "common.yaml").read_text(encoding="utf-8"))


def _merged(env_name: str) -> dict[str, Any]:
    """`common | combine(<env>, recursive=True)`, as the plays build `config`."""

    def combine(a: Any, b: Any) -> Any:
        if isinstance(a, dict) and isinstance(b, dict):
            return {**a, **{k: combine(a.get(k), v) for k, v in b.items()}}
        return b

    return combine(_common(), yaml.safe_load((VALUES / f"{env_name}.yaml").read_text(encoding="utf-8")) or {})


def _expression(value: str) -> str:
    """The expression inside a whole-value `{{ ... }}` template string."""
    value = value.strip()
    assert value.startswith("{{") and value.endswith("}}"), f"not a single expression: {value!r}"
    return value[2:-2].strip()


def coredns_role_vars() -> dict[str, Any]:
    """Every `coredns` role default, resolved against common.yaml as Ansible would (lazily, by passes)."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    env = _env()
    ctx: dict[str, Any] = {"common": _common(), "role_path": str(ROLE)}

    def render(value: Any) -> Any:
        if isinstance(value, str) and "{{" in value:
            stripped = value.strip()
            if stripped.startswith("{{") and stripped.endswith("}}") and stripped.count("{{") == 1:
                return env.compile_expression(_expression(stripped), undefined_to_none=False)(**ctx)
            return env.from_string(value).render(**ctx)
        if isinstance(value, dict):
            return {k: render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [render(v) for v in value]
        return value

    pending = dict(defaults)
    for _ in range(len(pending) + 1):
        progressed = False
        for key in list(pending):
            try:
                ctx[key] = render(pending[key])
            except jinja2.UndefinedError:
                continue
            del pending[key]
            progressed = True
        if not pending or not progressed:
            break
    assert "staging_zones" not in pending, f"the role's staging_zones default did not resolve: {pending}"
    return ctx


def rendered_corefile() -> str:
    text = (ROLE / "templates/Corefile.j2").read_text(encoding="utf-8")
    return _env().from_string(text).render(**coredns_role_vars())


def rendered_pihole_forwarding() -> str:
    text = (ROLE / "templates/pihole-forwarding.conf.j2").read_text(encoding="utf-8")
    return _env().from_string(text).render(**coredns_role_vars())


def headscale_split() -> dict[str, list[str]]:
    """`_headscale_dns_split` as the `deploy-vps.yml` task builds it, from that task's own `loop`."""
    play = yaml.safe_load((PLAYBOOKS / "deploy-vps.yml").read_text(encoding="utf-8"))[0]
    [task] = [t for t in play["pre_tasks"] if "split DNS" in t.get("name", "")]
    config = _merged(play["vars"]["deploy_env"])
    ctx = {"config": config, "playbook_dir": str(PLAYBOOKS)}
    zones = _env().compile_expression(_expression(task["loop"]))(**ctx)
    item_value = _expression(task["set_fact"]["_headscale_dns_split"])
    assert "combine({item: [config.networking.nodes.rpi4.tailscale_ip]})" in item_value, item_value
    return {zone: [config["networking"]["nodes"]["rpi4"]["tailscale_ip"]] for zone in zones}


def rendered_hairpin() -> str:
    """The pod-side hairpin ConfigMap's staging blocks, rendered by the toolkit path `make deploy-k8s` uses."""
    from toolkit.cli.infra import _staging_zones
    from toolkit.features.k8s_render import render_staging_zones

    return render_staging_zones(COREDNS_CUSTOM.read_text(encoding="utf-8"), _staging_zones())
