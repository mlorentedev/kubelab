"""What the GCP hub can read at boot, declared once and asserted here.

GCP-001 finding F1, ADR-063 D7. A managed instance group *recreates* rather than
restarts, so every preemption rebuilds the hub from a fresh disk with no operator
present. The rebuilt machine has no SOPS age key, no kubeconfig and nobody to
type a password -- Secret Manager is the only channel it can reach, and whatever
is not there is not recoverable at 3am.

That makes the tagged set a contract with two readers that never meet: the sync
tool writes it, and a cloud-init running months later reads it. Both sides being
right at the same time is what these assertions are for.

The expected set below is written out as LITERALS on purpose. Deriving it from
`SECRET_CATALOG` would compute the expected value from the actual one and pass by
construction -- the failure class `lesson-357` catalogues, which this repository
found four times in two days. A literal list means adding a secret to the hub's
boot path costs one deliberate edit here, which is the point: it is a widening of
what a public-cloud VM can read, and it should not be possible to do by accident.
"""

from __future__ import annotations

from toolkit.features.secrets_manager import (
    SECRET_CATALOG,
    secrets_synced_to_secret_manager,
)

# Every SOPS-authored secret the hub reads at boot. See the module docstring for
# why this is a literal rather than a comprehension.
EXPECTED_SYNCED = {
    # Read by cloud-init itself, before K3s exists: recycles the stale Headscale
    # node so the given-name is reused, then mints a single-use pre-auth key
    # rather than carrying a stored one (finding F2).
    "gcp.headscale_api_key",
    # The four the Argo CD Helm install needs. Today `_deploy-argocd-helm` reads
    # them from SOPS on an operator's workstation; a recreated hub has neither.
    "argocd.admin_password_hash",
    "apps.services.security.authelia.oidc_client_secret_argocd",
    "argocd.slack_webhook_url",
    "argocd.github_webhook_secret",
}


def _synced_keys() -> set[str]:
    return {s.key_path for s in secrets_synced_to_secret_manager()}


def test_the_synced_set_is_exactly_what_the_hub_needs_to_boot() -> None:
    """Both directions matter, and they fail for opposite reasons.

    Missing an entry means a recreated hub cannot finish its own bootstrap and
    the failure surfaces at the worst possible moment -- unattended, after a
    preemption. An extra entry means a Spot VM with a public IP can read a
    credential nothing on it uses, which is a widened blast radius nobody chose.
    """
    assert _synced_keys() == EXPECTED_SYNCED, (
        "the set of secrets delivered to Secret Manager has drifted from what "
        "this test declares. Adding one widens what a public-cloud VM can read, "
        "so it is a deliberate edit here, never an incidental tag on a SecretSpec."
    )


def test_every_synced_secret_is_audited_in_prod() -> None:
    """`envs` is the audit dimension, and the hub lives in prod.

    A synced secret scoped to some other env would be delivered to the hub and
    still be absent from the audit that is supposed to notice it missing --
    exactly the silent gap ANSIBLE-033 documents for `envs=("common",)`, which
    matches no real env at all.
    """
    for spec in secrets_synced_to_secret_manager():
        assert "prod" in spec.envs, (
            f"{spec.key_path} is delivered to the hub's Secret Manager but is "
            f"not audited in prod (envs={spec.envs}). `make secrets-audit` would "
            f"report the hub complete while the value it boots from is missing."
        )


def test_every_synced_secret_says_what_rotating_it_costs() -> None:
    """Rotation is where the one-way copy leaks if nobody wrote down the second step.

    SOPS stays the SSOT, so a rotation updates SOPS and Secret Manager still
    holds the old value until the sync runs again. A `rotate_note` that stops at
    "update common.enc.yaml" describes a rotation that has not reached the hub.
    """
    for spec in secrets_synced_to_secret_manager():
        assert spec.rotate_note, (
            f"{spec.key_path} is delivered to Secret Manager with no rotate_note. "
            f"Rotating it in SOPS alone leaves the hub booting from the old value."
        )


def test_the_gcp_headscale_key_is_not_confused_with_a_preauth_key() -> None:
    """The distinction is finding F2, and the names are one character apart in use.

    `aws1` baked a long-lived PRE-AUTH key into user_data. Under a MIG that key
    would sit in the template until it expired, after which a recreated VM would
    silently never join the mesh. The hub therefore stores an API key and mints
    its own pre-auth key per boot, and a future edit registering a pre-auth key
    for the GCP hub would be reintroducing the defect this design removed.
    """
    keys = {s.key_path for s in SECRET_CATALOG}
    assert "gcp.headscale_api_key" in keys, "the hub's boot credential is not registered"
    assert "gcp.headscale_preauth_key" not in keys, (
        "a pre-auth key is registered for the GCP hub. cloud-init mints its own, "
        "single-use and short-lived (finding F2); a stored one expires inside the "
        "MIG's instance template and the next recreate silently never joins the mesh."
    )


def test_no_two_synced_secrets_collide_on_their_secret_manager_id() -> None:
    """The name mapping is not injective, so uniqueness is asserted, not assumed.

    `secret_manager_name` collapses both `.` and `_` to `-`, because a Secret
    Manager id rejects a dot. That makes `a.b_c` and `a.b.c` the same id. Secret
    Manager has a flat namespace and no notion of two secrets sharing a name, so
    a collision does not error: the second write lands as a new VERSION of the
    first, and the hub boots with one secret's value under another's name.

    Nothing collides today. This test exists so that a future addition fails
    here, at the moment someone adds it, rather than unattended after a
    preemption.

    The union of BOTH input classes is checked. Checking only the catalog would
    miss exactly the interesting case -- a SOPS key colliding with a
    spoke-derived pseudo-path, which are declared in different files by
    different people.
    """
    from toolkit.features.secrets_manager import secret_manager_name

    spoke_paths = [
        f"argocd.spokes.{env}.{field}" for env in ("staging", "prod") for field in ("token", "ca")
    ]
    all_paths = sorted(EXPECTED_SYNCED) + spoke_paths
    ids = [secret_manager_name(p) for p in all_paths]

    duplicates = {name for name in ids if ids.count(name) > 1}
    assert not duplicates, (
        f"these SOPS paths map to the same Secret Manager id: {sorted(duplicates)}. "
        f"The second write would land as a new version of the first, and the hub "
        f"would boot with the wrong value under the right name."
    )
