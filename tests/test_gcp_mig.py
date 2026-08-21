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
            gcp_mig.status(config)
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
        with patch("toolkit.features.gcp_mig._list_instances") as ls, patch("toolkit.features.gcp_mig._run") as run:
            ls.return_value = ["gcp1-abcd"]
            run.return_value = 0
            gcp_mig.recreate(config)
        argv = _argv(run)
        assert "recreate-instances" in argv
        assert "--instances" in argv and "gcp1-abcd" in argv

    def test_an_empty_group_is_reported_not_silently_recreated(self, config: dict) -> None:
        """A MIG at size 0 has nothing to recreate. Calling gcloud anyway
        succeeds trivially and reports a recreate that never happened."""
        with patch("toolkit.features.gcp_mig._list_instances") as ls, patch("toolkit.features.gcp_mig._run") as run:
            ls.return_value = []
            with pytest.raises(RuntimeError, match="no instance"):
                gcp_mig.recreate(config)
            run.assert_not_called()


class TestNoCredentialIsEverPassed:
    def test_no_command_carries_a_secret_flag(self, config: dict) -> None:
        """The MIG surface needs none: the instance authenticates to Secret
        Manager with its own service account."""
        with patch("toolkit.features.gcp_mig._run") as run:
            run.return_value = 0
            gcp_mig.status(config)
            gcp_mig.resize(config, 1)
        for call in run.call_args_list:
            joined = " ".join(call[0][0])
            assert not any(f in joined for f in ("--password", "--key", "--token", "--secret"))
