"""Infrastructure: the declared Actions runner is registered and online, on the LIVE forge.

A runner is the one CI component whose absence is silent. A workflow whose `runs-on`
matches no runner is **queued, not failed**: Gitea reports no error, publishes no red
check, and the pull request simply never gets an answer. Every other failure in this
stack announces itself; this one looks like nothing happening.

Nothing else here can see it either. The compose template proves the service is
declared, the render test proves the labels are emitted, and `changed=0` on a
re-provision proves the file did not move — none of them can tell you the container
registered. And registration is exactly where it breaks: the mint is gated on a SOPS
key, so a token that drifted from the one Gitea holds produces a container that starts,
logs a rejection, restarts, and reports `Up` the whole time.

**A container reporting healthy says nothing about whether it registered** — the same
distinction as #959's "a container reporting healthy says nothing about whether its
port is reachable". Health probes run inside the process; registration is state on the
other side of the connection. Only the forge knows.
"""

from __future__ import annotations

import os

import pytest
import yaml

pytestmark = pytest.mark.infra

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_COMMON_YAML = os.path.abspath(os.path.join(_REPO_ROOT, "infra/config/values/common.yaml"))

#: Set in `compose.yml.j2`. The runner's identity on the forge, and what makes "is
#: OUR runner registered" a different question from "is ANY runner registered" — a
#: leftover record from a decommissioned node would answer the second one yes.
RUNNER_NAME = "kubelab-bee-gitea"


def _common() -> dict:
    with open(_COMMON_YAML, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="module")
def runners() -> list[dict]:
    """Every runner the forge has registered, or a skip if the forge is not up.

    The Beelink is on-demand (ADR-028), so "the forge is not answering" is a normal
    state rather than a finding. It is also indistinguishable from "no runner is
    registered" unless the two are separated here — and reporting a powered-off node
    as a CI outage is the false alarm that teaches people to ignore this suite.
    """
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.gitea_client import GiteaClient, GiteaError

    cfg = ConfigurationManager(env="prod")
    token = cfg.get_secret_by_path("apps.services.core.gitea.admin_token")
    if not token:
        pytest.skip("no Gitea admin token in SOPS — cannot ask the forge")

    domain = _common()["apps"]["services"]["core"]["gitea"]["domain"]
    try:
        return GiteaClient(f"https://{domain}", str(token)).list_runners()
    except GiteaError as exc:
        if exc.status_code and exc.status_code >= 500:
            pytest.skip(f"Gitea unreachable ({exc}) — the Beelink is on-demand")
        raise
    except OSError as exc:
        pytest.skip(f"Gitea unreachable ({exc}) — the Beelink is on-demand")


def test_the_declared_runner_is_registered(runners: list[dict]) -> None:
    """By NAME, not by count.

    "at least one runner exists" passes on a stale record left by a node that no
    longer exists — the shape the fleet already hit with `aws1`, whose Headscale
    record outlived the machine by ten days. Asserting the name is what makes this a
    statement about *this* runner.
    """
    names = [r.get("name") for r in runners]

    assert RUNNER_NAME in names, (
        f"`{RUNNER_NAME}` is not registered with the forge; it holds {names or 'no runners'}.\n"
        "CI jobs will QUEUE rather than fail, so nothing else will report this. Check "
        "the container's logs for a rejected registration token — the mint is gated on "
        "the SOPS key being absent, so a token that drifted from the one Gitea holds "
        "produces a container that reports `Up` and registers nothing."
    )


def test_the_registered_runner_can_serve_the_migrated_workflows(runners: list[dict]) -> None:
    """It advertises the label those workflows ask for.

    Registration is necessary and not sufficient: a runner registered with the wrong
    labels is online, healthy, visible in the UI, and picks up nothing. Read from the
    SSOT rather than repeated here, so the assertion follows a deliberate change to
    the mapping instead of failing on one.
    """
    declared = _common()["apps"]["services"]["automation"]["gitea_runner"]["labels"]
    wanted = str(declared).split(":", 1)[0]

    ours = [r for r in runners if r.get("name") == RUNNER_NAME]
    if not ours:
        pytest.skip("runner not registered — covered by the test above, not re-reported here")

    labels = ours[0].get("labels") or []
    names = [lbl.get("name") if isinstance(lbl, dict) else str(lbl) for lbl in labels]

    assert any(str(n).split(":", 1)[0] == wanted for n in names), (
        f"the runner is registered but advertises {names}, not `{wanted}`. Workflows "
        "migrated from GitHub say `runs-on: ubuntu-latest`, and a job matching no "
        "label is queued indefinitely rather than failed.\n"
        "Labels are recorded AT REGISTRATION: changing them in config.yaml does not "
        "update an already-registered runner, which is why this reads the forge."
    )


def test_no_undeclared_runner_is_registered(runners: list[dict]) -> None:
    """A stale record is a real cost, not untidiness.

    Every registered runner is a row the scheduler considers when placing a job. One
    that no longer exists takes work it will never run, and the job waits for a
    machine that is gone — again with no error. Deregistering is
    `make gitea-prune-runners APPLY=1`.
    """
    strays = [r.get("name") for r in runners if r.get("name") != RUNNER_NAME]

    assert not strays, (
        f"runners registered that this repository does not declare: {strays}. "
        "A job placed on a runner that no longer exists waits forever. Remove them "
        "with `make gitea-prune-runners APPLY=1`, or declare them if they are real."
    )
