"""Tests for k8s_render — cluster-wide bootstrap render-and-apply primitive (TOOL-009)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toolkit.features import k8s_render
from toolkit.features.k8s_render import (
    BootstrapEntry,
    RenderError,
    render_and_apply,
    render_text,
    resolve_magicdns,
)


def _ok(*stdouts: str) -> MagicMock:
    """subprocess.run mock returning rc=0 for each call in order."""
    return MagicMock(side_effect=[MagicMock(returncode=0, stdout=o, stderr="") for o in stdouts])


def _fail(stderr: str = "boom") -> MagicMock:
    return MagicMock(return_value=MagicMock(returncode=1, stdout="", stderr=stderr))


def _write(tmp: Path, body: str, name: str = "m.yaml") -> Path:
    (tmp / name).write_text(body)
    return tmp


# ── BootstrapEntry.from_dict ────────────────────────────────────────────────────


class TestFromDict:
    def test_minimal_entry(self) -> None:
        e = BootstrapEntry.from_dict({"name": "x", "namespace": "ns", "manifest": "a/b.yaml"})
        assert (e.name, e.namespace, e.manifest) == ("x", "ns", "a/b.yaml")
        assert e.version is None and e.optional is False and e.render == {}

    def test_versioned_operator(self) -> None:
        e = BootstrapEntry.from_dict(
            {"name": "agent-sandbox", "namespace": "agent-sandbox-system", "manifest": "m.yaml", "version": "v0.5.0rc1"}
        )
        assert e.version == "v0.5.0rc1"

    def test_render_and_optional(self) -> None:
        e = BootstrapEntry.from_dict(
            {
                "name": "coredns-custom",
                "namespace": "kube-system",
                "manifest": "c.yaml",
                "optional": True,
                "render": {"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"},
            }
        )
        assert e.optional is True
        assert e.render == {"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"}

    def test_entry_is_frozen(self) -> None:
        e = BootstrapEntry.from_dict({"name": "x", "namespace": "ns", "manifest": "m"})
        with pytest.raises(FrozenInstanceError):
            e.name = "mutated"  # type: ignore[misc]


# ── render_text (pure) ──────────────────────────────────────────────────────────


class TestRenderText:
    def test_substitutes_placeholder(self) -> None:
        out = render_text(
            "forward . RESOLVE_RPI4_TAILSCALE_IP\n",
            {"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"},
            resolver=lambda h: "100.64.0.10",
        )
        assert out == "forward . 100.64.0.10\n"
        assert "RESOLVE_" not in out

    def test_substitutes_all_occurrences(self) -> None:
        out = render_text(
            "a RESOLVE_X b RESOLVE_X c",
            {"RESOLVE_X": "h"},
            resolver=lambda h: "1.2.3.4",
        )
        assert out == "a 1.2.3.4 b 1.2.3.4 c"

    def test_unmapped_placeholder_raises(self) -> None:
        with pytest.raises(RenderError, match="unmapped"):
            render_text("RESOLVE_GHOST here", {}, resolver=lambda h: "1.1.1.1")

    def test_unresolvable_target_raises(self) -> None:
        with pytest.raises(RenderError, match="did not resolve"):
            render_text("RESOLVE_X", {"RESOLVE_X": "down.host"}, resolver=lambda h: None)

    def test_noop_when_no_placeholders(self) -> None:
        # render_map entry whose placeholder is absent must not call resolver
        resolver = MagicMock(return_value="1.1.1.1")
        out = render_text("plain text", {"RESOLVE_X": "h"}, resolver=resolver)
        assert out == "plain text"
        resolver.assert_not_called()


# ── render_and_apply ────────────────────────────────────────────────────────────


class TestRenderAndApply:
    def _entry(self, **kw: object) -> BootstrapEntry:
        base = {"name": "coredns-custom", "namespace": "kube-system", "manifest": "m.yaml"}
        base.update(kw)
        return BootstrapEntry.from_dict(base)

    def test_happy_path_dry_run_then_apply(self, tmp_path: Path) -> None:
        _write(tmp_path, "forward . RESOLVE_RPI4_TAILSCALE_IP\n")
        runner = _ok("dry ok", "configmap/coredns-custom serverside-applied")
        ok = render_and_apply(
            self._entry(optional=True, render={"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"}),
            kubeconfig="/kc",
            project_root=tmp_path,
            resolver=lambda h: "100.64.0.10",
            runner=runner,
        )
        assert ok is True
        assert runner.call_count == 2  # client-validate then server-apply
        # 1st call is a client-side validation (no namespace dependency); IP reached stdin
        first_cmd, first_kwargs = runner.call_args_list[0]
        assert "--dry-run=client" in first_cmd[0]
        assert "--server-side" not in first_cmd[0]
        assert "100.64.0.10" in first_kwargs["input"]
        # 2nd call is the real server-side apply (no dry-run flag)
        second_cmd, _ = runner.call_args_list[1]
        assert "--server-side" in second_cmd[0]
        assert "--dry-run=client" not in second_cmd[0]

    def test_dry_run_only_skips_apply(self, tmp_path: Path) -> None:
        _write(tmp_path, "kind: ConfigMap\n")
        runner = _ok("dry ok")
        ok = render_and_apply(
            self._entry(),
            kubeconfig="/kc",
            project_root=tmp_path,
            dry_run=True,
            runner=runner,
        )
        assert ok is True
        assert runner.call_count == 1

    def test_optional_skip_when_unresolvable(self, tmp_path: Path) -> None:
        _write(tmp_path, "forward . RESOLVE_RPI4_TAILSCALE_IP\n")
        runner = MagicMock()
        ok = render_and_apply(
            self._entry(optional=True, render={"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"}),
            kubeconfig="/kc",
            project_root=tmp_path,
            resolver=lambda h: None,  # node off
            runner=runner,
        )
        assert ok is True
        runner.assert_not_called()  # nothing applied

    def test_required_render_failure_returns_false(self, tmp_path: Path) -> None:
        _write(tmp_path, "forward . RESOLVE_RPI4_TAILSCALE_IP\n")
        runner = MagicMock()
        ok = render_and_apply(
            self._entry(optional=False, render={"RESOLVE_RPI4_TAILSCALE_IP": "rpi4.kubelab.internal"}),
            kubeconfig="/kc",
            project_root=tmp_path,
            resolver=lambda h: None,
            runner=runner,
        )
        assert ok is False
        runner.assert_not_called()

    def test_missing_manifest_returns_false(self, tmp_path: Path) -> None:
        runner = MagicMock()
        ok = render_and_apply(
            self._entry(manifest="nope.yaml"),
            kubeconfig="/kc",
            project_root=tmp_path,
            runner=runner,
        )
        assert ok is False
        runner.assert_not_called()

    def test_dry_run_failure_skips_apply(self, tmp_path: Path) -> None:
        _write(tmp_path, "kind: ConfigMap\n")
        runner = _fail("invalid")
        ok = render_and_apply(
            self._entry(),
            kubeconfig="/kc",
            project_root=tmp_path,
            runner=runner,
        )
        assert ok is False
        assert runner.call_count == 1  # failed dry-run → no apply

    def test_apply_failure_returns_false(self, tmp_path: Path) -> None:
        _write(tmp_path, "kind: ConfigMap\n")
        # dry-run ok, apply fails
        runner = MagicMock(
            side_effect=[
                MagicMock(returncode=0, stdout="dry ok", stderr=""),
                MagicMock(returncode=1, stdout="", stderr="conflict"),
            ]
        )
        ok = render_and_apply(
            self._entry(),
            kubeconfig="/kc",
            project_root=tmp_path,
            runner=runner,
        )
        assert ok is False
        assert runner.call_count == 2

    def test_no_render_map_applies_verbatim(self, tmp_path: Path) -> None:
        _write(tmp_path, "kind: Namespace\nmetadata:\n  name: agent-sandbox-system\n")
        runner = _ok("dry ok", "applied")
        ok = render_and_apply(
            BootstrapEntry.from_dict(
                {
                    "name": "agent-sandbox",
                    "namespace": "agent-sandbox-system",
                    "manifest": "m.yaml",
                    "version": "v0.5.0rc1",
                }
            ),
            kubeconfig="/kc",
            project_root=tmp_path,
            runner=runner,
        )
        assert ok is True
        assert runner.call_count == 2


# ── resolve_magicdns (dig wrapper) ──────────────────────────────────────────────


class TestResolveMagicDNS:
    def test_returns_first_answer_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            k8s_render.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout="100.64.0.10\n", stderr=""),
        )
        assert resolve_magicdns("rpi4.kubelab.internal") == "100.64.0.10"

    def test_skips_blank_lines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            k8s_render.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout="\n100.64.0.7\n", stderr=""),
        )
        assert resolve_magicdns("aws1.kubelab.internal") == "100.64.0.7"

    def test_none_on_empty_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            k8s_render.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout="", stderr=""),
        )
        assert resolve_magicdns("ghost.host") is None

    def test_none_on_dig_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            k8s_render.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=1, stdout="", stderr="err"),
        )
        assert resolve_magicdns("x") is None

    def test_none_when_dig_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a: object, **k: object) -> None:
            raise FileNotFoundError("dig")

        monkeypatch.setattr(k8s_render.subprocess, "run", _raise)
        assert resolve_magicdns("x") is None
