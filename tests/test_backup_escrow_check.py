"""`make backup-escrow-check` fails when the offsite escrow cannot restore what SOPS encrypts with (BACKUP-057 AC5).

The escrow is the only copy that survives the loss of the age key, and nothing
else reads it, so a stale entry is found on the day it is needed. Bitwarden is
read through `dotf secrets probe`, which reports a sha256[:12] fingerprint and
never a value; the SOPS side is hashed in-process. Faked here: what is asserted
is that a stale, missing or unreadable entry fails, and that no value is ever
in the output.
"""

from __future__ import annotations

import hashlib
import pathlib
from typing import Any

import pytest
import yaml

from toolkit.features import backup_escrow as be
from toolkit.features.backup_node_credentials import restic_password_path

REPO = pathlib.Path(__file__).resolve().parents[1]
NODES = ["beelink", "rpi3", "rpi4", "vps"]
SHARED = "backup.restic_password"


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _sops() -> dict[str, str]:
    return {SHARED: "fixture-shared"} | {restic_password_path(n): f"fixture-{n}" for n in NODES}


def _probe_output(value: str | None) -> str:
    password = f"  data.login.password                len={len(value)}    {_fp(value)}\n" if value else ""
    return (
        "HTTP 200  application/json; charset=utf-8  695 bytes\n"
        "envelope: success=true\n"
        "values (never printed — length and fingerprint only):\n"
        "  data.id                          len=36    f5c08365510c\n" + password
    )


class Escrow:
    def __init__(self) -> None:
        self.values: dict[str, str | None] = {be.escrow_id(None): "fixture-shared"} | {
            be.escrow_id(n): f"fixture-{n}" for n in NODES
        }
        self.asked: list[str] = []
        self.fail: dict[str, tuple[int, str]] = {}

    def run(self, argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        assert argv[:3] == ["dotf", "secrets", "probe"]
        entry = argv[3]
        self.asked.append(entry)
        if entry in self.fail:
            rc, err = self.fail[entry]
            return rc, "", err
        return 0, _probe_output(self.values.get(entry)), ""


def _check(escrow: Escrow, sops: dict[str, str] | None = None) -> bool:
    return be.check(NODES, secret=(sops if sops is not None else _sops()).get, run=escrow.run)


def test_the_escrow_ids_are_the_registrys() -> None:
    assert be.escrow_id(None) == "KUBELAB_RESTIC_PASSWORD"
    assert be.escrow_id("rpi3") == "KUBELAB_RESTIC_PASSWORD_RPI3"


def test_a_current_escrow_passes_and_every_password_was_compared() -> None:
    escrow = Escrow()
    assert _check(escrow) is True
    assert sorted(escrow.asked) == sorted(escrow.values)


def test_a_stale_entry_fails_it() -> None:
    escrow = Escrow()
    escrow.values[be.escrow_id("rpi4")] = "fixture-rpi4-before-rotation"
    assert _check(escrow) is False


def test_an_entry_without_a_password_fails_it() -> None:
    escrow = Escrow()
    escrow.values[be.escrow_id("vps")] = None
    assert _check(escrow) is False


def test_an_output_format_it_cannot_read_is_not_reported_as_a_missing_password(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    escrow = Escrow()
    real = escrow.run

    def reformatted(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        rc, out, err = real(argv, env)
        return rc, out.replace("len=", "length: "), err

    assert be.check(NODES, secret=_sops().get, run=reformatted) is False
    out = capsys.readouterr().out + caplog.text
    assert "output format changed" in out
    assert "MISSING in the escrow" not in out


def test_an_unreadable_escrow_fails_it_and_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    escrow = Escrow()
    escrow.fail[be.escrow_id("beelink")] = (1, "bw serve: vault is locked")
    assert _check(escrow) is False
    assert "dotf secrets unlock" in capsys.readouterr().out


def test_a_password_missing_from_sops_fails_it() -> None:
    sops = _sops()
    del sops[restic_password_path("rpi3")]
    escrow = Escrow()
    assert _check(escrow, sops) is False
    # Said as what it is, not as a stale escrow compared against nothing.
    assert be.escrow_id("rpi3") not in escrow.asked


class _CM:
    """The merged config check_fleet reads: values plus SOPS, here with fixture passwords."""

    def __init__(self, sources: list[str], in_sops: list[str]) -> None:
        self.config = {
            "backup": {
                "restic_password": "fixture-shared",
                "sources": {n: {} for n in sources},
                "nodes": {n: {"restic_password": f"fixture-{n}", "r2": {}} for n in in_sops},
            }
        }

    def get_merged_config(self) -> dict[str, Any]:
        return self.config

    def get_secret_by_path(self, path: str) -> str | None:
        node: Any = self.config
        for key in path.split("."):
            node = node.get(key) if isinstance(node, dict) else None
        return node if isinstance(node, str) else None


def test_the_fleet_is_the_committed_backup_sources() -> None:
    committed = sorted(yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())["backup"]["sources"])
    escrow = Escrow()
    for n in committed:
        escrow.values.setdefault(be.escrow_id(n), f"fixture-{n}")
    assert be.check_fleet("prod", cm=_CM(committed, committed), run=escrow.run) is True
    assert sorted(escrow.asked) == sorted([be.escrow_id(None), *(be.escrow_id(n) for n in committed)])


def test_an_empty_fleet_fails_it_instead_of_comparing_only_the_shared_password() -> None:
    escrow = Escrow()
    assert be.check_fleet("prod", cm=_CM([], NODES), run=escrow.run) is False
    assert escrow.asked == []


def test_a_password_left_in_sops_after_its_node_left_is_compared_too() -> None:
    escrow = Escrow()
    escrow.values[be.escrow_id("rpi4")] = "fixture-rpi4-before-rotation"
    assert be.check_fleet("prod", cm=_CM(["beelink", "rpi3", "vps"], NODES), run=escrow.run) is False
    assert be.escrow_id("rpi4") in escrow.asked


def test_a_source_without_a_password_in_sops_fails_it_and_is_named_as_sops() -> None:
    # backup.sources is consulted, not only the SOPS key set: rpi4 has no password there.
    escrow = Escrow()
    assert be.check_fleet("prod", cm=_CM(NODES, ["beelink", "rpi3", "vps"]), run=escrow.run) is False
    assert be.escrow_id("rpi4") not in escrow.asked


def test_the_target_defaults_to_prod() -> None:
    recipe = (REPO / "Makefile").read_text().split("\nbackup-escrow-check:\n", 1)[1].split("\n\n", 1)[0]
    assert "backup escrow-check --env $(or $(filter staging prod,$(ENV)),prod)" in recipe


@pytest.mark.parametrize("stale", [None, "rpi3"])
def test_no_value_reaches_the_output(
    stale: str | None, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    escrow = Escrow()
    if stale:
        escrow.values[be.escrow_id(stale)] = "fixture-other"
    _check(escrow)
    out = capsys.readouterr()
    text = caplog.text + out.out + out.err
    assert not [v for v in [*_sops().values(), "fixture-other"] if v in text]
