"""A restore drill run on another host from the workstation (BACKUP-071 AC2, AC3).

The workstation resolves every input, SOPS included, and hands the drill to
`toolkit backup drill-<x> --inputs-stdin` on the host over the ssh session's
stdin. These tests pin what may travel where: no secret in argv, nothing
written to disk, no config read on the host, and a refused start when the tree
the run would vouch for is not the one on `origin`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tests.test_headscale_drill import IMAGE, STAGING, _Fake
from toolkit.cli.backup import app
from toolkit.features import drill_remote, gitea_drill, headscale_drill
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.headscale_drill import read_live

REPO = Path(__file__).resolve().parents[1]
SHA = "0123456789abcdef0123456789abcdef01234567"

#: Distinctive values standing in for every secret the workstation injects.
SENTINELS = {
    "RESTIC_PASSWORD": "sentinel-restic-9f3a",
    "AWS_ACCESS_KEY_ID": "sentinel-r2-id-51c0",
    "AWS_SECRET_ACCESS_KEY": "sentinel-r2-secret-7d2e",
}
TOKEN = "sentinel-gitea-token-c48b"


def _gitea_inputs() -> dict:
    return {
        "repo": "s3:https://e/b/kubelab-bee",
        "restic_env": dict(SENTINELS),
        "staging_dir": STAGING,
        "image": "gitea/gitea:1.24.6",
        "admin_user": "manu",
        "gitea_url": "https://git.kubelab.live",
        "token": TOKEN,
    }


def _headscale_inputs() -> dict:
    live = read_live(_Fake(), "manu@vps", "headscale_headscale_data")
    assert live is not None
    return {
        "repo": "s3:https://e/b/kubelab-vps",
        "restic_env": dict(SENTINELS),
        "staging_dir": STAGING,
        "image": IMAGE,
        "cidr": "100.64.0.0/10",
        "live": live.to_payload(),
    }


class _Stream:
    """Plays `ssh host script` with the payload on stdin. Records what it was given."""

    def __init__(self, rc: int = 0) -> None:
        self.rc = rc
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, argv: list[str], *, stdin: str) -> int:
        self.calls.append((argv, stdin))
        return self.rc


def _all_secrets() -> list[str]:
    return [*SENTINELS.values(), TOKEN]


# --- What the workstation sends -------------------------------------------


@pytest.mark.parametrize("drill, inputs", [("gitea", _gitea_inputs), ("headscale", _headscale_inputs)])
def test_no_injected_value_reaches_the_ssh_argv_and_the_payload_goes_on_stdin(drill, inputs) -> None:
    stream = _Stream()
    assert drill_remote.run_remote(drill, inputs(), target="manu@100.64.0.5", sha=SHA, stream=stream)
    [(argv, stdin)] = stream.calls
    assert argv[0] == "ssh" and "manu@100.64.0.5" in argv
    joined = " ".join(argv)
    assert not [s for s in _all_secrets() if s in joined], "a secret in argv is visible in `ps` on both ends"
    assert f"drill-{drill} --inputs-stdin" in joined
    assert SHA in joined, "the host must run the commit the workstation vouches for"
    payload = json.loads(stdin)
    assert payload["drill"] == drill
    assert payload["inputs"]["restic_env"] == SENTINELS


def test_the_remote_script_keeps_stdin_for_the_drill() -> None:
    """`git fetch` and `make worktree-init` run first; any of them could eat the payload."""
    script = drill_remote.remote_script("headscale", SHA)
    *setup, last = [line for line in script.splitlines() if line.strip()]
    assert last.startswith("exec "), "the drill's exit code must be the ssh exit code"
    for line in setup:
        if any(cmd in line for cmd in ("git ", "make ", "poetry ")):
            assert "</dev/null" in line, f"this step would read the payload: {line}"


@pytest.mark.parametrize("sha", ["HEAD", "abc; rm -rf ~", "0123456789abcdef"])
def test_only_a_full_commit_id_reaches_the_remote_shell(sha) -> None:
    with pytest.raises(ValueError):
        drill_remote.remote_script("gitea", sha)


@pytest.mark.parametrize(
    "rc, expected, named",
    [
        (0, True, None),
        (1, False, None),
        (255, False, "CANNOT CHECK — could not reach"),
        (drill_remote.SETUP_FAILED, False, "CANNOT CHECK — the drill checkout could not be prepared"),
    ],
    ids=["pass", "drill-failed", "unreachable", "setup-failed"],
)
def test_each_exit_class_is_reported_as_itself(capsys, rc, expected, named) -> None:
    ok = drill_remote.run_remote("gitea", _gitea_inputs(), target="manu@ace2", sha=SHA, stream=_Stream(rc))
    assert ok is expected
    out = " ".join(capsys.readouterr().out.split())
    if named:
        assert named in out
    assert not [s for s in _all_secrets() if s in out]


def test_the_checkout_path_is_the_one_dev_node_provisions() -> None:
    defaults = yaml.safe_load((REPO / "infra/ansible/roles/dev_node/defaults/main.yml").read_text())
    assert defaults["dev_node_drill_checkout"] == "{{ dev_node_home }}/" + drill_remote.CHECKOUT


def test_the_host_resolves_to_its_tailnet_address_and_homelab_user() -> None:
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    net = common["networking"]
    assert (
        drill_remote.ssh_target(net, "ace2") == f"{net['ssh_users']['homelab']}@{net['nodes']['ace2']['tailscale_ip']}"
    )
    with pytest.raises(KeyError):
        drill_remote.ssh_target(net, "no-such-node")


# --- Preflight: the run vouches for a commit origin has --------------------


def _git(porcelain: str = "", remote_branches: str = "  origin/feat/x\n", rc: int = 0):
    calls: list[list[str]] = []

    def run(argv: list[str], *, env=None):
        calls.append(argv)
        if "status" in argv:
            return rc, porcelain, ""
        if "--contains" in argv:
            return rc, remote_branches, ""
        if "rev-parse" in argv:
            return rc, SHA + "\n", ""
        return 0, "", ""

    run.calls = calls  # type: ignore[attr-defined]
    return run


@pytest.mark.parametrize(
    "git, named",
    [
        (_git(porcelain=" M toolkit/features/gitea_drill.py\n"), "the tree has uncommitted changes"),
        (_git(porcelain="?? scratch.txt\n"), "the tree has uncommitted changes"),
        (_git(remote_branches=""), "origin does not have"),
        (_git(rc=128), "git"),
    ],
    ids=["modified", "untracked", "unpushed", "git-fails"],
)
def test_a_tree_origin_cannot_reproduce_refuses_before_any_ssh(monkeypatch, capsys, git, named) -> None:
    stream = _Stream()
    resolved = []
    monkeypatch.setattr(gitea_drill, "resolve_inputs", lambda env, root: resolved.append(env) or _gitea_inputs())
    ok = drill_remote.drill_on_host("gitea", env="prod", host="ace2", project_root=REPO, git=git, stream=stream)
    assert ok is False
    out = " ".join(capsys.readouterr().out.split())
    assert "CANNOT CHECK" in out and named in out
    assert not stream.calls, "nothing may reach the host"
    assert not resolved, "SOPS is not opened for a run that cannot happen"


def test_a_clean_pushed_tree_sends_its_head(monkeypatch) -> None:
    stream = _Stream()
    monkeypatch.setattr(gitea_drill, "resolve_inputs", lambda env, root: _gitea_inputs())
    assert drill_remote.drill_on_host("gitea", env="prod", host="ace2", project_root=REPO, git=_git(), stream=stream)
    [(argv, _)] = stream.calls
    assert SHA in " ".join(argv)


def test_inputs_that_cannot_be_resolved_send_nothing(monkeypatch) -> None:
    stream = _Stream()
    monkeypatch.setattr(headscale_drill, "resolve_inputs", lambda env, root: None)
    assert not drill_remote.drill_on_host(
        "headscale", env="prod", host="ace2", project_root=REPO, git=_git(), stream=stream
    )
    assert not stream.calls


# --- What the host runs ------------------------------------------------------


@pytest.fixture
def no_config(monkeypatch):
    """The host has no SOPS key: building a ConfigurationManager there is a defect."""

    def refuse(self, *a, **kw):
        raise AssertionError("the remote entrypoint built a ConfigurationManager")

    monkeypatch.setattr(ConfigurationManager, "__init__", refuse)


@pytest.mark.parametrize("drill, inputs", [("gitea", _gitea_inputs), ("headscale", _headscale_inputs)])
def test_the_entrypoint_runs_the_drill_with_the_payload_and_reads_no_config(monkeypatch, no_config, drill, inputs):
    module = {"gitea": gitea_drill, "headscale": headscale_drill}[drill]
    seen: dict = {}
    monkeypatch.setattr(module, "run_drill", lambda **kw: seen.update(kw) or True)
    sent = inputs()
    result = CliRunner().invoke(
        app, [f"drill-{drill}", "--inputs-stdin"], input=json.dumps({"drill": drill, "inputs": sent})
    )
    assert result.exit_code == 0, result.output
    assert seen["repo"] == sent["repo"] and seen["restic_env"] == SENTINELS and seen["image"] == sent["image"]
    if drill == "gitea":
        assert seen["live"].token == TOKEN and seen["live"].base_url == sent["gitea_url"]
    else:
        assert seen["live"] == headscale_drill.LiveState.from_payload(sent["live"])


def test_a_real_restore_on_the_host_writes_no_injected_value_to_disk(tmp_path, monkeypatch, no_config) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    fake = _Fake()
    ticks = iter(range(0, 100_000, 5))
    monkeypatch.setattr(headscale_drill, "_default_run", fake)
    monkeypatch.setattr(headscale_drill.time, "sleep", lambda s: None)
    monkeypatch.setattr(headscale_drill.time, "monotonic", lambda: float(next(ticks)))
    # Read every file the drill wrote at the moment it tears its tree down.
    real_rmtree = headscale_drill.shutil.rmtree
    written: list[Path] = []
    leaked: list[str] = []

    def inspect_then_remove(path, *a, **kw):
        for f in Path(path).rglob("*"):
            if f.is_file():
                written.append(f)
                leaked.extend(str(f) for s in _all_secrets() if s.encode() in f.read_bytes())
        return real_rmtree(path, *a, **kw)

    monkeypatch.setattr(headscale_drill.shutil, "rmtree", inspect_then_remove)
    payload = json.dumps({"drill": "headscale", "inputs": _headscale_inputs()})
    result = CliRunner().invoke(app, ["drill-headscale", "--inputs-stdin"], input=payload)
    assert result.exit_code == 0, result.output
    written += [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written, "the fake restore wrote nothing, so this test would prove nothing"
    leaked += [str(p) for p in written if p.exists() for s in _all_secrets() if s.encode() in p.read_bytes()]
    assert not leaked


@pytest.mark.parametrize(
    "text",
    [
        '{"drill": "gitea", "inputs": {"restic_env": {"RESTIC_PASSWORD": "sentinel-restic-9f3a"}',
        json.dumps({"drill": "gitea", "inputs": {"restic_env": SENTINELS, "token": TOKEN}}),
        json.dumps({"drill": "headscale", "inputs": {**_gitea_inputs()}}),
        json.dumps(["sentinel-restic-9f3a"]),
    ],
    ids=["truncated", "missing-fields", "wrong-drill", "not-an-object"],
)
def test_a_malformed_payload_fails_without_echoing_any_of_it(capsys, no_config, text) -> None:
    result = CliRunner().invoke(app, ["drill-gitea", "--inputs-stdin"], input=text)
    assert result.exit_code != 0
    shown = result.output + " ".join(capsys.readouterr())
    assert "CANNOT CHECK" in shown
    assert not [s for s in _all_secrets() if s in shown]


def test_host_and_inputs_stdin_together_are_refused(no_config) -> None:
    result = CliRunner().invoke(app, ["drill-gitea", "--inputs-stdin", "--host", "ace2"], input="{}")
    assert result.exit_code != 0
