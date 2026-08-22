"""MIG lifecycle: status, resize, recreate. Every gcloud call is mocked.

Nothing here reaches real GCP and nothing can until a project exists -- `gcloud`
is not installed on this workstation and no runner is authenticated. So these
guards are about the SHAPE of the commands, which is exactly where the mistakes
that matter live: the wrong scope flag against a REGIONAL group silently targets
nothing, and a recreate that names the group rather than an instance is a no-op
that reports success.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from toolkit.features import gcp_mig


@pytest.fixture
def config() -> dict:
    return {"networking": {"gcp": {"hostname": "gcp1", "region": "europe-west4", "project_id": "kubelab-hub"}}}


def _argv(mock) -> list[str]:
    return mock.call_args[0][0]


def _mi(instance_id: str, action: str = "NONE", status: str = "RUNNING") -> list[dict]:
    """One managed instance, in the shape `list-instances --format=json` returns."""
    return [
        {
            "instance": "https://example/instances/gcp1-abcd",
            "name": "gcp1-abcd",
            "id": instance_id,
            "instanceStatus": status,
            "currentAction": action,
        }
    ]


class TestItAddressesTheRegionalGroup:
    """A regional MIG answers to `--region`. Passing `--zone`, or omitting both,
    makes gcloud look for a group that does not exist -- and the failure names a
    missing resource rather than a wrong flag."""

    def test_resize_is_scoped_by_region_never_zone(self, config: dict) -> None:
        with patch("toolkit.features.gcp_mig._run") as run:
            run.return_value = 0
            gcp_mig.resize(config, 0)
        argv = _argv(run)
        assert "--region" in argv and "europe-west4" in argv
        assert "--zone" not in argv

    def test_the_group_name_is_derived_from_the_ssot_hostname(self, config: dict) -> None:
        """`${var.hostname}-mig` in main.tf. A literal here would go stale the
        first time the hostname changes, and only at apply time."""
        with patch("toolkit.features.gcp_mig._run") as run:
            run.return_value = 0
            gcp_mig.resize(config, 1)
        assert "gcp1-mig" in _argv(run)

    def test_the_project_is_always_passed_explicitly(self, config: dict) -> None:
        """gcloud's ambient default project is whatever the operator last set.
        A resize against the wrong project is not an error, it is a resize."""
        with patch("toolkit.features.gcp_mig._run") as run:
            run.return_value = 0
            gcp_mig.resize(config, 1)
        assert "--project" in _argv(run)


class TestResize:
    def test_stop_is_size_zero_not_a_delete(self, config: dict) -> None:
        """Deleting the MIG loses the template and the recreate contract with it.
        Size 0 stops the billing and keeps the machine that rebuilds it."""
        with patch("toolkit.features.gcp_mig._run") as run:
            run.return_value = 0
            gcp_mig.resize(config, 0)
        argv = _argv(run)
        assert "resize" in argv and "--size" in argv and "0" in argv
        assert "delete" not in argv

    def test_a_negative_size_is_refused_before_it_reaches_gcloud(self, config: dict) -> None:
        with patch("toolkit.features.gcp_mig._run") as run:
            with pytest.raises(ValueError, match="size"):
                gcp_mig.resize(config, -1)
            run.assert_not_called()

    def test_a_size_above_one_is_refused(self, config: dict) -> None:
        """The hub is a singleton: two Argo CD controllers on one spoke is the
        exact failure the single-writer invariant exists to prevent, and a
        fat-fingered `--size 2` is the cheapest way to cause it."""
        with patch("toolkit.features.gcp_mig._run") as run:
            with pytest.raises(ValueError, match="singleton"):
                gcp_mig.resize(config, 2)
            run.assert_not_called()


class TestRecreate:
    def test_it_names_an_instance_not_the_group(self, config: dict) -> None:
        """`recreate-instances` needs `--instances`. Without it gcloud rejects
        the call, but a helper that passed the group name would look right."""
        # `_managed_instances`, not `_list_instances`: recreate now compares
        # instance IDs to know the replacement finished, so it reads the full
        # managed-instance objects. Two polls — one showing the old id, one the
        # new — so the wait is exercised rather than skipped.
        with (
            patch("toolkit.features.gcp_mig._managed_instances", side_effect=[_mi("1"), _mi("2")]),
            patch("toolkit.features.gcp_mig._run") as run,
            patch("toolkit.features.gcp_mig.time.sleep"),
        ):
            run.return_value = 0
            gcp_mig.recreate(config)
        argv = _argv(run)
        assert "recreate-instances" in argv
        assert "--instances" in argv and "gcp1-abcd" in argv

    def test_an_empty_group_is_reported_not_silently_recreated(self, config: dict) -> None:
        """A MIG at size 0 has nothing to recreate. Calling gcloud anyway
        succeeds trivially and reports a recreate that never happened."""
        with (
            patch("toolkit.features.gcp_mig._managed_instances", return_value=[]),
            patch("toolkit.features.gcp_mig._run") as run,
        ):
            with pytest.raises(RuntimeError, match="no instance"):
                gcp_mig.recreate(config)
            run.assert_not_called()


class TestNoCredentialIsEverPassed:
    def test_no_command_carries_a_secret_flag(self, config: dict) -> None:
        """The MIG surface needs none: the instance authenticates to Secret
        Manager with its own service account."""
        with (
            patch("toolkit.features.gcp_mig._run") as run,
            patch("toolkit.features.gcp_mig._list_instances", return_value=["gcp1-abcd"]),
            patch("toolkit.features.gcp_mig._managed_instances", side_effect=[_mi("1"), _mi("2")]),
            patch("toolkit.features.gcp_mig.time.sleep"),
            patch("toolkit.features.k8s_render.resolve_magicdns", return_value="100.64.0.12"),
        ):
            run.return_value = 0
            gcp_mig.status(config)
            gcp_mig.resize(config, 1)
            gcp_mig.recreate(config)
        for call in run.call_args_list:
            joined = " ".join(call[0][0])
            assert not any(f in joined for f in ("--password", "--key", "--token", "--secret"))


class TestStatusReportsWhatTheRunbookPromises:
    """docs/runbooks/gcp-hub-bootstrap.md §8 says `gcp1-status` shows MIG state,
    instance state and a `dig` of the MagicDNS name. A `describe` alone reports
    the group's opinion of itself, which is exactly the fact that stays healthy
    while the node fails to join the mesh."""

    def test_it_reports_the_instances_and_resolves_the_magicdns_name(self, config: dict) -> None:
        with (
            patch("toolkit.features.gcp_mig._run", return_value=0),
            patch("toolkit.features.gcp_mig._list_instances", return_value=["gcp1-abcd"]) as ls,
            patch("toolkit.features.k8s_render.resolve_magicdns", return_value="100.64.0.12") as dig,
        ):
            assert gcp_mig.status(config) == 0
        ls.assert_called_once()
        dig.assert_called_once_with("gcp1.kubelab.internal")

    def test_an_unresolvable_name_is_reported_without_failing_the_command(self, config: dict) -> None:
        """A stopped hub legitimately does not resolve. Exiting non-zero would
        make `gcp1-status` unusable for the state it exists to report."""
        with (
            patch("toolkit.features.gcp_mig._run", return_value=0),
            patch("toolkit.features.gcp_mig._list_instances", return_value=[]),
            patch("toolkit.features.k8s_render.resolve_magicdns", return_value=None),
        ):
            assert gcp_mig.status(config) == 0

    def test_a_failed_describe_short_circuits(self, config: dict) -> None:
        """No point digging for a name whose group could not even be read."""
        with (
            patch("toolkit.features.gcp_mig._run", return_value=1),
            patch("toolkit.features.gcp_mig._list_instances") as ls,
        ):
            assert gcp_mig.status(config) == 1
        ls.assert_not_called()


class TestRecreateWaitsForTheMachineItAskedFor:
    """`recreate-instances` returns when the request is ACCEPTED, not when it is done.

    Measured 2026-08-22 running the full `make gcp1-replace` chain. gcloud
    printed `SUCCESS` immediately, `wait-node-ready` ran next and connected to
    the OLD VM -- still alive, still answering -- and cached its host key. By the
    time `provision` ran, the replacement had happened and the host key had
    changed, so ssh refused and the play hung for six minutes on its first probe.

    #1265's host-key purge is correct and fired; what was wrong is WHEN. Purging
    before the machine has actually been replaced just caches the dying VM's key.

    The instance NAME cannot detect this: `replacement_method = RECREATE`
    preserves it deliberately (the given-name collision hazard). The numeric `id`
    does change, and `list-instances --format=json` returns it -- verified
    against the live group mid-recreate:

        {"name": "gcp1-bxjh", "id": "7978086404576288333",
         "instanceStatus": "STAGING", "currentAction": "RECREATING"}

    So the contract is: the recreate is done when every instance reports
    `currentAction: NONE`, `instanceStatus: RUNNING`, and an id that is NOT one
    of the ids observed before the request.
    """

    @staticmethod
    def _managed(instance_id: str, action: str = "NONE", status: str = "RUNNING") -> list[dict]:
        return [
            {
                "instance": "https://example/instances/gcp1-bxjh",
                "name": "gcp1-bxjh",
                "id": instance_id,
                "instanceStatus": status,
                "currentAction": action,
            }
        ]

    def test_it_does_not_return_while_the_id_is_unchanged(self, config: dict) -> None:
        """The old VM answering is the whole failure mode, so it must not satisfy the wait."""
        polls = [
            self._managed("111", action="RECREATING", status="STOPPING"),
            self._managed("111", action="RECREATING", status="STAGING"),
            self._managed("222"),  # replaced
        ]
        seen = []

        def fake_managed(_config):  # noqa: ANN001, ANN202
            seen.append(len(seen))
            return polls[min(len(seen) - 1, len(polls) - 1)]

        with (
            patch("toolkit.features.gcp_mig._managed_instances", side_effect=fake_managed),
            patch("toolkit.features.gcp_mig._run", return_value=0),
            patch("toolkit.features.gcp_mig.time.sleep"),
        ):
            gcp_mig.recreate(config)

        assert len(seen) >= 3, (
            "recreate returned before the instance id changed. gcloud reports SUCCESS "
            "on acceptance, so returning then hands the next step a VM that is about "
            "to be destroyed — and its host key with it."
        )

    def test_it_does_not_accept_a_new_id_that_is_still_being_built(self, config: dict) -> None:
        """RUNNING and NONE both matter: a STAGING instance has no sshd yet."""
        # The FIRST call is the before-snapshot, so its id is what "old" means.
        # An earlier draft started at 222 and thereby declared the replacement's
        # own id stale, so the wait could never be satisfied and the test hung
        # for the full ten-minute timeout. The fixture has to model the sequence
        # the function actually sees, not just the states it cares about.
        polls = [
            self._managed("111"),  # before-snapshot
            self._managed("222", action="CREATING", status="STAGING"),
            self._managed("222"),
        ]
        seen = []

        def fake_managed(_config):  # noqa: ANN001, ANN202
            seen.append(len(seen))
            return polls[min(len(seen) - 1, len(polls) - 1)]

        with (
            patch("toolkit.features.gcp_mig._managed_instances", side_effect=fake_managed),
            patch("toolkit.features.gcp_mig._run", return_value=0),
            patch("toolkit.features.gcp_mig.time.sleep"),
        ):
            gcp_mig.recreate(config)

        assert len(seen) >= 3, "it accepted an instance still reporting CREATING/STAGING"

    def test_it_gives_up_rather_than_waiting_for_ever(self, config: dict) -> None:
        """A stuck replacement must fail loudly, not hang the chain silently."""
        with (
            patch("toolkit.features.gcp_mig._managed_instances", return_value=self._managed("111")),
            patch("toolkit.features.gcp_mig._run", return_value=0),
            patch("toolkit.features.gcp_mig.time.sleep"),
            pytest.raises(RuntimeError, match="did not replace"),
        ):
            gcp_mig.recreate(config, timeout_s=1)
