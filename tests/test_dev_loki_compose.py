"""Dev Loki must not carry a healthcheck its image cannot run, nor gate Vector on it.

`grafana/loki` 3.x is distroless: no `/bin/sh`, no `wget`. The dev healthcheck was
`CMD-SHELL wget ...`, so it could never pass, and Vector waited on
`service_healthy` forever, sitting in `created` while Loki answered `/ready` 200.
Hidden until 2026-09-26 because the dev container predated the 3.6.4 pin and was
never recreated. K8s has no start ordering either: Vector retries its sink, and
Loki's readiness is the `httpGet` probe there, so `service_started` is parity.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((REPO / "infra/stacks/services/observability/loki/compose.base.yml").read_text())


def test_loki_has_no_shell_healthcheck() -> None:
    test = (COMPOSE["services"]["loki"].get("healthcheck") or {}).get("test") or []
    assert "CMD-SHELL" not in test, "the Loki image has no shell, so this check can never pass"


def test_vector_does_not_wait_for_loki_health() -> None:
    depends = COMPOSE["services"]["vector"].get("depends_on") or {}
    condition = (depends.get("loki") or {}).get("condition") if isinstance(depends, dict) else None
    assert condition != "service_healthy", "Vector would sit in `created` until a check that cannot pass"
