"""Where the forge credential travels, asserted on what actually leaves the process.

The property this module exists to hold is negative -- "the password is not on the
command line" -- and a negative property is exactly the kind that passes vacuously.
So each one is paired with the positive that proves the assertion had something to
look at, per lesson-416: an empty argv contains no secret, and an empty environment
carries none either.

No git runs. `run_git` takes its runner as an argument precisely so the argv and
the env can be captured and asserted directly, rather than inferred from a fake's
answer (lesson-423).
"""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features.gitea_git import (
    BASE_CONFIG,
    CREDENTIAL_HELPER,
    GiteaGitError,
    build_argv,
    build_env,
    resolve_git_credential,
    run_git,
)

PASSWORD = "correct-horse-battery-staple"
ADMIN_TOKEN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
BOT_TOKEN = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def merged(**overrides: Any) -> dict[str, Any]:
    gitea = {
        "domain": "gitea.example.invalid",
        "admin_token": ADMIN_TOKEN,
        "bot_token": BOT_TOKEN,
        "admin_password": PASSWORD,
        **overrides,
    }
    return {
        "apps": {
            "services": {"core": {"gitea": gitea}},
            "auth": {"identities": {"superadmin": "manu", "machine": "hefesto"}},
        }
    }


class _Capturing:
    """Stands in for `subprocess.run`, recording what it was handed."""

    def __init__(self, returncode: int = 0) -> None:
        self.argv: list[str] | None = None
        self.env: dict[str, str] | None = None
        self.cwd: str | None = None
        self._returncode = returncode

    def __call__(self, argv: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> Any:
        self.argv = argv
        self.env = env
        self.cwd = cwd
        return type("Proc", (), {"returncode": self._returncode})()


def test_the_password_is_never_on_the_command_line() -> None:
    """A command line is readable by every user on the host through `ps`.

    Care taken anywhere else does not compensate for this, so it is asserted on the
    argv itself rather than on the behaviour of whatever consumes it.
    """
    runner = _Capturing()
    run_git(["push", "origin", "HEAD"], merged(), runner=runner)

    assert runner.argv is not None
    flat = " ".join(runner.argv)
    assert PASSWORD not in flat
    assert ADMIN_TOKEN not in flat and BOT_TOKEN not in flat
    # The floor: without this the assertion above would hold over an empty argv.
    assert runner.argv[0] == "git" and runner.argv[-3:] == ["push", "origin", "HEAD"]


def test_the_password_reaches_the_child_environment() -> None:
    """The positive half. Keeping it off the command line is only useful if it arrives."""
    runner = _Capturing()
    run_git(["status"], merged(), runner=runner)

    assert runner.env is not None
    assert runner.env["GITEA_GIT_PASS"] == PASSWORD
    assert runner.env["GITEA_GIT_USER"] == "manu"


def test_git_must_fail_rather_than_prompt() -> None:
    """Fail-closed on both fallbacks.

    A run that blocks forever on an invisible prompt is what makes people paste a
    token onto a command line, so the failure mode has to be an error.
    """
    runner = _Capturing()
    run_git(["fetch"], merged(), runner=runner)

    assert runner.env is not None
    assert runner.env["GIT_TERMINAL_PROMPT"] == "0"
    assert runner.env["GIT_ASKPASS"] == "/bin/false"


def test_the_credential_is_the_admin_password_and_not_a_token() -> None:
    """Measured 2026-09-04: neither token may push, and one of them must never be able to.

    `admin_token` is refused at Gitea's scope layer because it has no
    `write:repository` -- a scope this line of work keeps off every token on
    purpose, since it is a standing DELETE capability. Asserting the identity of the
    chosen credential here is what stops a later edit from "simplifying" this to the
    token the rest of the module already holds.
    """
    user, password = resolve_git_credential(merged())

    assert (user, password) == ("manu", PASSWORD)
    assert password not in (ADMIN_TOKEN, BOT_TOKEN)


def test_an_absent_password_is_refused_with_the_reason() -> None:
    """And the message says why a token is not a substitute, because that is the next thing tried."""
    with pytest.raises(GiteaGitError) as exc:
        resolve_git_credential(merged(admin_password=None))

    assert "write:repository" in str(exc.value)


def test_the_helper_is_marked_as_a_shell_command() -> None:
    """The leading `!`. Without it git looks for a program named `git-credential-f() {...}`.

    It fails with a shell syntax error that names nothing, and the run then dies on
    `could not read Username` -- which reads as a missing credential rather than a
    malformed helper. Measured while writing the probe this module came from.
    """
    assert CREDENTIAL_HELPER.startswith("!")
    assert "$GITEA_GIT_PASS" in CREDENTIAL_HELPER, "the helper must read the password from the environment"
    assert PASSWORD not in CREDENTIAL_HELPER


def test_the_shared_hooks_path_is_neutralised() -> None:
    """This repository sets `core.hooksPath` GLOBALLY, so every clone inherits its hooks.

    Measured: a push probe against `personal/resume` ran kubelab's
    trailing-whitespace hook, which modified files in that clone and aborted the
    push -- with an exit code indistinguishable from a permission refusal.
    """
    argv = build_argv(["push"])

    assert "core.hooksPath=/dev/null" in argv
    assert argv.index("core.hooksPath=/dev/null") < argv.index("push"), "config must precede the subcommand"


def test_every_base_config_flag_survives_into_the_command() -> None:
    """Anti-vacuity on the derived argv, not on the constant that feeds it.

    `BASE_CONFIG` going empty would leave both assertions above with nothing to
    check while `build_argv` still returned a runnable command -- the exact shape
    lesson-416 names. So assert the FLOOR on what was built.
    """
    argv = build_argv(["log"])

    assert BASE_CONFIG, "BASE_CONFIG is empty; every configuration assertion here matches everything"
    for flag in BASE_CONFIG:
        assert flag in argv


def test_the_exit_code_is_git_s_own() -> None:
    """A caller scripting this must be able to tell a failed push from a successful one."""
    assert run_git(["push"], merged(), runner=_Capturing(returncode=0)) == 0
    assert run_git(["push"], merged(), runner=_Capturing(returncode=128)) == 128


def test_the_ambient_environment_is_preserved() -> None:
    """git needs PATH, HOME and SSH_AUTH_SOCK; replacing the environment breaks it.

    Passed explicitly rather than read from `os.environ`, so the test says what it
    depends on instead of inheriting it.
    """
    env = build_env("manu", PASSWORD, base_env={"PATH": "/usr/bin", "HOME": "/home/manu"})

    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/manu"
    assert env["GITEA_GIT_PASS"] == PASSWORD
