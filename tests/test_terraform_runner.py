"""Every Terraform invocation goes through one runner (TF-007, #558).

Before the runner, each `tf-*` Make target carried its own copy of the same
sequence: render a tfvars into the module directory, export a token, `cd`,
`terraform init`, the verb, then remove the file in the same shell line so a
failed plan could not leave it behind (TOOL-039). Nine copies of that sequence
drifted the way copies do. The remote backend (TF-007 PR 1b) adds two more
things to every invocation, the backend file and its credentials, and an eleventh
copy of anything is the wrong place to add them.

These tests drive the runner with a recording fake in place of `terraform`, so
what is asserted is the command line, the child's environment and the files on
disk at the moment terraform runs. None of it needs the binary or a credential.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features import terraform_runner as tr

REPO = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO / "infra" / "terraform"

SECRET = "secret-sentinel-value"

SECRET_PATHS = (
    "cloudflare.api_token",
    "cloudflare.r2_admin_token",
    "hetzner.api_key",
    "aws.headscale_preauth_key",
    "aws.headscale_api_key",
    "gcp.billing_account_id",
)


def _config() -> dict[str, Any]:
    """The real plaintext SSOT, with every secret the roots read set to SECRET."""
    config = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))
    for path in SECRET_PATHS:
        node = config
        *parents, leaf = path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = SECRET
    return config


CONFIG = _config()


def _on_disk(path: Path) -> tuple[bool, int | None]:
    return (True, path.stat().st_mode & 0o777) if path.exists() else (False, None)


class FakeTerraform:
    """Records each call and answers with a scripted exit code per subcommand."""

    def __init__(self, fail: dict[str, int] | None = None, plan_json: dict | None = None, stdout: str = "") -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail or {}
        self.plan_json = plan_json if plan_json is not None else {"resource_changes": []}
        self.stdout = stdout

    def __call__(self, args: list[str], *, env: dict[str, str], capture: bool, quiet: bool) -> tr.Result:
        verb = args[1] if args[0].startswith("-chdir=") else args[0]
        # What exists on disk WHILE terraform runs, for the files the runner
        # promised to remove afterwards.
        var_files = [a.split("=", 1)[1] for a in args if a.startswith("-var-file=")]
        self.calls.append(
            {
                "args": list(args),
                "verb": verb,
                "env": dict(env),
                "capture": capture,
                "quiet": quiet,
                "var_files": {p: _on_disk(Path(p)) for p in var_files},
            }
        )
        rc = self.fail.get(verb, 0)
        if verb == "show":
            return tr.Result(rc, json.dumps(self.plan_json))
        return tr.Result(rc, self.stdout if capture else "")

    def verbs(self) -> list[str]:
        return [c["verb"] for c in self.calls]

    def call(self, verb: str) -> dict[str, Any]:
        [match] = [c for c in self.calls if c["verb"] == verb]
        return match


def _run(root: str, action: str, fake: FakeTerraform, tmp_path: Path | None = None, **kwargs: Any) -> int:
    terraform_dir = kwargs.pop("terraform_dir", TERRAFORM_DIR)
    return tr.run(
        root,
        action,
        terraform_dir=terraform_dir,
        load_config=lambda: CONFIG,
        terraform=fake,
        **kwargs,
    )


# --------------------------------------------------------------------------- the registry


def test_every_registered_root_is_a_module_on_disk() -> None:
    for name in tr.ROOTS:
        assert (TERRAFORM_DIR / name / "main.tf").is_file(), name


def test_every_module_on_disk_is_a_registered_root() -> None:
    """The other direction. compute/ had no root, so the only way to run the DR
    module was by hand, around the secret handling (review of #2236)."""
    on_disk = {p.parent.name for p in TERRAFORM_DIR.glob("*/main.tf")}
    assert on_disk == set(tr.ROOTS), on_disk ^ set(tr.ROOTS)


@pytest.mark.parametrize("name", sorted(tr.ROOTS))
def test_every_injected_secret_is_a_declared_variable(name: str) -> None:
    """A `TF_VAR_x` with no `variable "x"` is ignored by Terraform without a word."""
    declared = set(re.findall(r'^variable\s+"(\w+)"', (TERRAFORM_DIR / name / "variables.tf").read_text(), re.M))
    assert set(tr.ROOTS[name].secrets) <= declared, set(tr.ROOTS[name].secrets) - declared


@pytest.mark.parametrize("name", sorted(tr.ROOTS))
def test_every_committed_var_file_exists(name: str) -> None:
    """A missing `-var-file` stops the plan before it reads anything; catch it here instead."""
    for var_file in tr.ROOTS[name].var_files:
        assert (TERRAFORM_DIR / name / var_file).is_file(), var_file


def test_an_unknown_root_is_refused_before_anything_runs() -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="unknown root"):
        _run("nope", "plan", fake)
    assert fake.calls == []


def test_an_unknown_action_is_refused_before_anything_runs() -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match="unknown action"):
        _run("dns", "taint", fake)
    assert fake.calls == []


# --------------------------------------------------------------------------- init, every time


@pytest.mark.parametrize("action", ["plan", "apply", "destroy", "output", "untaint"])
def test_init_runs_first_and_quietly(action: str) -> None:
    """A fresh clone or worktree has no `.terraform/`; the verb alone fails there."""
    fake = FakeTerraform()
    _run("gcp", action, fake, extra=["x"] if action == "untaint" else [])
    assert fake.verbs()[0] == "init"
    assert fake.calls[0]["quiet"]
    assert "-input=false" in fake.calls[0]["args"]


def test_a_failed_init_stops_the_run_and_its_code_reaches_the_caller() -> None:
    fake = FakeTerraform(fail={"init": 3})
    assert _run("gcp", "plan", fake) == 3
    assert fake.verbs() == ["init"]


def test_every_call_targets_the_module_directory() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    for call in fake.calls:
        assert call["args"][0] == f"-chdir={TERRAFORM_DIR / 'dns'}"


# --------------------------------------------------------------------------- secrets


def test_secrets_reach_the_child_environment_and_never_argv() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    plan = fake.call("plan")
    assert plan["env"]["TF_VAR_cloudflare_api_token"] == SECRET
    assert not any(SECRET in a for a in plan["args"])


def test_r2_uses_the_r2_token_not_the_dns_one() -> None:
    """The DNS token is refused by the R2 bucket API (2026-10-02)."""
    assert tr.ROOTS["r2"].secrets == {"cloudflare_api_token": "cloudflare.r2_admin_token"}
    assert tr.ROOTS["dns"].secrets == {"cloudflare_api_token": "cloudflare.api_token"}


def test_a_missing_secret_is_named_and_nothing_runs() -> None:
    fake = FakeTerraform()
    with pytest.raises(tr.RunnerError, match=r"cloudflare\.api_token"):
        tr.run("dns", "plan", terraform_dir=TERRAFORM_DIR, load_config=lambda: {}, terraform=fake)
    assert fake.calls == []


def test_inherited_aws_and_tf_var_variables_are_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inputs come from the SSOT only. A shell's `AWS_PROFILE` or a stale
    `TF_VAR_x` would otherwise outrank it without anything saying so."""
    monkeypatch.setenv("AWS_PROFILE", "someone-else")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "stale")
    monkeypatch.setenv("TF_VAR_region", "us-east-1")
    monkeypatch.setenv("KEEP_ME", "1")
    fake = FakeTerraform()
    _run("gcp", "plan", fake)
    env = fake.call("plan")["env"]
    assert not [k for k in env if k.startswith(("AWS_", "TF_VAR_"))]
    assert env["KEEP_ME"] == "1"


@pytest.mark.parametrize(
    "name",
    [
        "TF_CLI_ARGS_apply",  # `-auto-approve` here would apply past the plan guard
        "TF_CLI_ARGS",
        "TF_LOG",  # trace logging prints the injected TF_VAR_ values
        "TF_LOG_PATH",
        "TF_WORKSPACE",  # a different state than the one the plan was read against
        "TF_DATA_DIR",
    ],
)
def test_no_inherited_tf_variable_changes_what_terraform_does(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "-auto-approve")
    fake = FakeTerraform()
    _run("dns", "apply", fake)
    assert all(name not in c["env"] for c in fake.calls)


def test_the_plugin_cache_is_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    """It only makes init faster; dropping it would download every provider again."""
    monkeypatch.setenv("TF_PLUGIN_CACHE_DIR", "/cache")
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    assert fake.call("init")["env"]["TF_PLUGIN_CACHE_DIR"] == "/cache"


# --------------------------------------------------------------------------- rendered tfvars


def test_the_rendered_tfvars_exists_while_terraform_runs_private_and_outside_the_module() -> None:
    fake = FakeTerraform()
    _run("gcp", "plan", fake)
    [(path, (existed, mode))] = fake.call("plan")["var_files"].items()
    assert existed and mode == 0o600
    assert not Path(path).is_relative_to(TERRAFORM_DIR)


@pytest.mark.parametrize(
    ("action", "fake"),
    [
        ("plan", FakeTerraform()),
        ("plan", FakeTerraform(fail={"plan": 1})),
        ("plan", FakeTerraform(fail={"init": 1})),
        ("apply", FakeTerraform()),
        ("apply", FakeTerraform(fail={"apply": 1})),
        ("apply", FakeTerraform(plan_json={"resource_changes": [{"address": "x.y", "change": {"actions": ["delete"]}}]})),
    ],
    ids=["plan", "plan-fails", "init-fails", "apply", "apply-fails", "guard-refuses"],
)
def test_the_private_directory_never_outlives_the_run(
    monkeypatch: pytest.MonkeyPatch, action: str, fake: FakeTerraform
) -> None:
    """The directory, not a file in it: it holds the render AND the saved plan,
    and the plan carries the token. Checked even when init fails, where no
    terraform call ever names the file."""
    made: list[Path] = []

    class Recording(tr.tempfile.TemporaryDirectory):  # type: ignore[type-arg]
        def __enter__(self) -> str:
            made.append(Path(self.name))
            return super().__enter__()

    monkeypatch.setattr(tr.tempfile, "TemporaryDirectory", Recording)
    _run("dns", action, fake)
    assert made and not any(p.exists() for p in made), made


def test_the_rendered_tfvars_is_removed_when_terraform_raises() -> None:
    seen: list[str] = []

    def boom(args: list[str], **_: Any) -> tr.Result:
        seen.extend(a.split("=", 1)[1] for a in args if a.startswith("-var-file="))
        if args[1] == "plan":
            raise KeyboardInterrupt
        return tr.Result(0, "")

    with pytest.raises(KeyboardInterrupt):
        tr.run("gcp", "plan", terraform_dir=TERRAFORM_DIR, load_config=lambda: CONFIG, terraform=boom)
    assert seen and not any(Path(p).exists() for p in seen)


def test_the_dns_root_reads_the_vps_address_from_the_ssot() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    rendered = [p for p in fake.call("plan")["var_files"] if not Path(p).is_relative_to(TERRAFORM_DIR)]
    assert len(rendered) == 1
    assert tr.ROOTS["dns"].render is not None
    content = tr.ROOTS["dns"].render(tr.Context(CONFIG, TERRAFORM_DIR / "dns", lambda *_: ""))
    assert content == f'vps_ip = "{CONFIG["networking"]["vps"]["public_ip"]}"\n'


def test_no_committed_var_file_sets_a_rendered_variable() -> None:
    """Two -var-files setting one variable: the last wins, silently, and the
    copy that loses goes stale without anything reading it."""
    dns = (TERRAFORM_DIR / "dns" / "dns.tfvars").read_text(encoding="utf-8")
    assert not re.search(r"^\s*vps_ip\s*=", dns, re.M)


def test_a_renderer_refusing_the_ssot_names_the_key_and_nothing_runs() -> None:
    fake = FakeTerraform()
    config = {**CONFIG, "networking": {}}
    with pytest.raises(tr.RunnerError, match=r"cannot render the dns inputs.*vps"):
        tr.run("dns", "plan", terraform_dir=TERRAFORM_DIR, load_config=lambda: config, terraform=fake)
    assert fake.calls == []


def test_committed_var_files_are_passed_from_the_module() -> None:
    fake = FakeTerraform()
    _run("dns", "plan", fake)
    assert f"-var-file={TERRAFORM_DIR / 'dns' / 'dns.tfvars'}" in fake.call("plan")["args"]


def test_a_stale_rendered_file_in_the_module_is_removed_first(tmp_path: Path) -> None:
    """Terraform auto-loads `*.auto.tfvars`, so a leftover from the old Make
    targets would still be read, silently, next to the fresh render."""
    module = tmp_path / "vps-firewall"
    module.mkdir()
    stale = module / "vps-firewall.auto.tfvars"
    stale.write_text("inbound_rules = []\n")
    fake = FakeTerraform()
    tr.run(
        "vps-firewall",
        "plan",
        terraform_dir=tmp_path,
        load_config=lambda: _firewall_config(),
        terraform=fake,
    )
    assert not stale.exists()


def _firewall_config() -> dict[str, Any]:
    return {
        **CONFIG,
        "networking": {
            "firewall": {"vps_inbound": [{"port": 22, "proto": "tcp", "description": "ssh"}]},
            "vps": {"hetzner_server_name": "vps", "public_ip": "192.0.2.1"},
        },
    }


# --------------------------------------------------------------------------- apply modes


def test_a_guarded_apply_saves_the_plan_checks_it_and_applies_that_file() -> None:
    fake = FakeTerraform()
    assert _run("dns", "apply", fake) == 0
    assert fake.verbs() == ["init", "plan", "show", "apply"]
    out = next(a for a in fake.call("plan")["args"] if a.startswith("-out="))
    planfile = out.split("=", 1)[1]
    assert fake.call("show")["args"][-1] == planfile
    assert fake.call("show")["capture"]
    assert fake.call("apply")["args"][-1] == planfile
    assert "-input=false" in fake.call("apply")["args"]
    assert not Path(planfile).exists(), "the saved plan holds the token; it must not outlive the run"


DELETE_PLAN = {
    "resource_changes": [
        {"address": 'cloudflare_record.kubelab_svc["old"]', "change": {"actions": ["delete"]}},
    ]
}


def test_a_guarded_apply_refuses_a_delete_and_never_applies() -> None:
    fake = FakeTerraform(plan_json=DELETE_PLAN)
    assert _run("dns", "apply", fake) == 1
    assert "apply" not in fake.verbs()


def test_allow_destroy_and_a_named_address_open_the_guard() -> None:
    fake = FakeTerraform(plan_json=DELETE_PLAN)
    assert _run("dns", "apply", fake, allow_destroy=True) == 0
    fake = FakeTerraform(plan_json=DELETE_PLAN)
    assert _run("dns", "apply", fake, allowed=['cloudflare_record.kubelab_svc["old"]']) == 0
    assert fake.verbs()[-1] == "apply"


def test_a_show_without_plan_json_applies_nothing() -> None:
    class NoJson(FakeTerraform):
        def __call__(self, args: list[str], **kw: Any) -> tr.Result:
            result = super().__call__(args, **kw)
            return tr.Result(0, "") if self.calls[-1]["verb"] == "show" else result

    fake = NoJson()
    assert _run("dns", "apply", fake) == 1
    assert "apply" not in fake.verbs()


def test_a_failed_plan_never_reaches_the_guard_or_the_apply() -> None:
    fake = FakeTerraform(fail={"plan": 1})
    assert _run("dns", "apply", fake) == 1
    assert fake.verbs() == ["init", "plan"]


@pytest.mark.parametrize("name", ["r2", "vps-firewall", "gcp-bootstrap"])
def test_an_interactive_root_asks_before_applying(name: str) -> None:
    """vps-firewall can lock the operator out of the VPS; r2's lock rules cannot
    be lifted by a node; gcp-bootstrap holds the billing guardrails."""
    assert tr.ROOTS[name].apply == "interactive"


def test_an_interactive_apply_leaves_the_prompt_to_terraform() -> None:
    fake = FakeTerraform()
    _run("gcp-bootstrap", "apply", fake)
    args = fake.call("apply")["args"]
    assert "-auto-approve" not in args and "-input=false" not in args


def test_only_the_disposable_fixture_applies_and_destroys_unattended() -> None:
    assert {n for n, r in tr.ROOTS.items() if r.apply == "auto"} == {"gcp-killswitch-test"}


def test_the_disposable_fixture_auto_approves() -> None:
    fake = FakeTerraform()
    tr.run(
        "gcp-killswitch-test",
        "apply",
        terraform_dir=TERRAFORM_DIR,
        load_config=lambda: CONFIG,
        terraform=fake,
        outputs=lambda root, name: "sa@example.iam.gserviceaccount.com",
    )
    assert "-auto-approve" in fake.call("apply")["args"]


@pytest.mark.parametrize("name", ["dns", "gcp", "aws", "r2"])
def test_destroy_always_asks_outside_the_fixture(name: str) -> None:
    fake = FakeTerraform()
    _run(name, "destroy", fake)
    assert "-auto-approve" not in fake.call("destroy")["args"]


def test_extra_arguments_reach_the_plan_of_a_guarded_apply() -> None:
    """aws1-replace names its replace; the guard lets exactly that one through."""
    fake = FakeTerraform()
    _run("aws", "apply", fake, extra=["-replace=aws_instance.argo_hub"], allowed=["aws_instance.argo_hub"])
    assert "-replace=aws_instance.argo_hub" in fake.call("plan")["args"]
    assert "-replace=aws_instance.argo_hub" not in fake.call("apply")["args"]


def test_extra_arguments_reach_an_interactive_apply() -> None:
    fake = FakeTerraform()
    _run("r2", "plan", fake, extra=["-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"])
    assert fake.call("plan")["args"][-2:] == ["-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"]


# --------------------------------------------------------------------------- state-only verbs


def test_output_passes_no_var_file_and_its_stdout_is_terraforms_alone() -> None:
    """`$(...)` captures it in Make, so nothing else may print on stdout."""
    fake = FakeTerraform()
    _run("aws", "output", fake, extra=["-raw", "spot_request_id"])
    call = fake.call("output")
    assert call["args"][1:] == ["output", "-raw", "spot_request_id"]
    assert not call["quiet"]


def test_untaint_needs_an_address() -> None:
    with pytest.raises(tr.RunnerError, match="address"):
        _run("dns", "untaint", FakeTerraform())


def test_untaint_touches_state_only() -> None:
    fake = FakeTerraform()
    _run("dns", "untaint", fake, extra=['cloudflare_record.kubelab_svc["chat"]'])
    assert fake.verbs() == ["init", "untaint"]


def test_output_reads_another_root_through_the_runner() -> None:
    """The fixture's tfvars needs the bootstrap root's service account."""
    fake = FakeTerraform(stdout="sa@example.iam.gserviceaccount.com\n")
    value = tr.output("gcp-bootstrap", "kill_switch_service_account", terraform_dir=TERRAFORM_DIR, terraform=fake)
    assert value == "sa@example.iam.gserviceaccount.com"
    assert fake.call("output")["args"][1:] == ["output", "-raw", "kill_switch_service_account"]


# --------------------------------------------------------------------------- the real subprocess seam


@pytest.mark.allow_host_clients(reason="spawns a stub `terraform` script first on PATH, never the real binary")
def test_the_default_terraform_seam_passes_the_environment_and_returns_the_code(tmp_path: Path) -> None:
    script = tmp_path / "terraform"
    script.write_text('#!/bin/sh\necho "$TF_VAR_x"\nexit 4\n')
    script.chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", "TF_VAR_x": "hello"}
    result = tr.subprocess_terraform(["version"], env=env, capture=True, quiet=False)
    assert (result.returncode, result.stdout.strip()) == (4, "hello")


def test_a_missing_binary_names_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def absent(*_: Any, **__: Any) -> None:
        raise FileNotFoundError("terraform")

    monkeypatch.setattr(tr.subprocess, "run", absent)
    with pytest.raises(tr.RunnerError, match="dotf tools sync"):
        tr.subprocess_terraform(["version"], env={}, capture=False, quiet=False)


# --------------------------------------------------------------------------- the command


def _invoke(monkeypatch: pytest.MonkeyPatch, argv: list[str], code: int = 0, raises: Exception | None = None):
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    seen: dict[str, Any] = {}

    def fake_run(root: str, action: str, **kwargs: Any) -> int:
        if raises:
            raise raises
        seen.update(root=root, action=action, **kwargs)
        return code

    monkeypatch.setattr(tr, "run", fake_run)
    return CliRunner().invoke(app, ["terraform", "run", *argv]), seen


def test_arguments_after_the_separator_reach_terraform(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Makefile's SCRATCH scope, the `-raw <name>` of an output, an untaint address."""
    result, seen = _invoke(
        monkeypatch, ["r2", "plan", "--", "-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"]
    )
    assert result.exit_code == 0, result.output
    assert (seen["root"], seen["action"]) == ("r2", "plan")
    assert seen["extra"] == ["-var=scratch=true", "-target=cloudflare_r2_bucket.scratch"]


def test_the_guard_options_reach_the_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    result, seen = _invoke(
        monkeypatch, ["aws", "apply", "--allow", "aws_instance.argo_hub", "--", "-replace=aws_instance.argo_hub"]
    )
    assert result.exit_code == 0, result.output
    assert list(seen["allowed"]) == ["aws_instance.argo_hub"]
    assert seen["extra"] == ["-replace=aws_instance.argo_hub"]
    assert seen["allow_destroy"] is False
    _, seen = _invoke(monkeypatch, ["dns", "apply", "--allow-destroy"])
    assert seen["allow_destroy"] is True and seen["extra"] == []


def test_terraforms_exit_code_is_the_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _invoke(monkeypatch, ["dns", "plan"], code=3)[0].exit_code == 3


def test_a_refused_start_exits_2_and_names_the_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _invoke(monkeypatch, ["nope", "plan"], raises=tr.RunnerError("unknown root 'nope'"))
    assert result.exit_code == 2 and "unknown root" in result.output


# --------------------------------------------------------------------------- the kill-switch proof


def _prove(
    monkeypatch: pytest.MonkeyPatch,
    *,
    apply_rc: int = 0,
    destroy_rc: int = 0,
    project: str = "kubelab-killswitch-1",
    verify_ok=True,
    raises: Exception | None = None,
):
    import typer
    from typer.testing import CliRunner

    from toolkit.cli import infra

    calls: list[str] = []

    def fake_run(root: str, action: str, **_: Any) -> int:
        calls.append(action)
        if raises is not None and action == "apply":
            raise raises
        return {"apply": apply_rc, "destroy": destroy_rc}[action]

    def fake_verify(scratch_project: str) -> None:
        calls.append(f"verify {scratch_project}")
        if not verify_ok:
            raise typer.Exit(1)

    monkeypatch.setattr(tr, "run", fake_run)
    monkeypatch.setattr(tr, "output", lambda root, name, **_: project)
    monkeypatch.setattr(infra, "tf_verify_killswitch", fake_verify)
    result = CliRunner().invoke(infra.app, ["terraform", "killswitch-prove"])
    return result, calls


def test_the_proof_tears_its_project_down_when_it_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, verify_ok=False)
    assert result.exit_code == 1
    assert calls == ["apply", "verify kubelab-killswitch-1", "destroy"]


def test_the_proof_tears_its_project_down_when_it_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch)
    assert result.exit_code == 0 and calls[-1] == "destroy"


def test_a_failed_apply_skips_the_proof_and_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed apply can have created the project before it failed."""
    result, calls = _prove(monkeypatch, apply_rc=1)
    assert result.exit_code == 1 and calls == ["apply", "destroy"]


def test_a_refused_start_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, raises=tr.RunnerError("cannot render"))
    assert result.exit_code == 1 and calls == ["apply", "destroy"]
    # Reported and exited, not a traceback the operator has to read past.
    assert isinstance(result.exception, SystemExit), result.exception


def test_a_proof_that_passed_but_left_its_project_behind_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, destroy_rc=1)
    assert result.exit_code == 1 and calls[-1] == "destroy"


def test_an_empty_project_output_is_a_failure_and_still_tears_down(monkeypatch: pytest.MonkeyPatch) -> None:
    result, calls = _prove(monkeypatch, project="")
    assert result.exit_code == 1 and calls == ["apply", "destroy"]
