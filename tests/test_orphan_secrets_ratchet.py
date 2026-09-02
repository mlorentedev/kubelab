"""The orphan baseline may only shrink, and an unbaselined orphan fails the audit.

**The debt this closes is not a missing check.** `orphan_key_paths` has detected
orphans for a while and `toolkit secrets audit` printed them and exited `0`. On
2026-09-01 prod carried seventeen of them, so when an eighteenth appeared — a real
Authelia password hash, written that evening and registered by nobody — nothing
distinguished it from the pile. A warning with seventeen permanent entries is not a
signal. That is lesson-306's shape: a check never observed failing is a claim.

So the fix is enforcement plus a container for the existing debt:

- the audit **exits non-zero** on any orphan not in the baseline;
- the baseline is a committed file, one line per orphan **with a reason**, so every
  line is a deletion-shaped follow-up rather than a silent accommodation;
- and it may only **shrink** — growing it means raising `ORPHAN_BASELINE_MAX` here,
  which is an explicit edit a reviewer sees, not something that happens by drift.

The ratchet constant is the whole mechanism. Without it, "add it to the baseline"
is as cheap as ignoring the warning was, and the noise returns one entry at a time.
"""

from __future__ import annotations

import pytest

from toolkit.features.secrets_manager import (
    ORPHAN_BASELINE_PATH,
    baselined_orphans,
    unbaselined_orphans,
)

#: The baseline holds this many entries. It began at 19 when the ratchet was
#: installed (2026-09-01) and came down to 16 the same day, when the three
#: test-residue keys were deleted from the vaults -- the ratchet moving in the
#: direction it exists for. **Lower it as orphans are resolved; raising it is the reviewable
#: act.** If you are here because a test failed after adding a baseline entry:
#: that is the mechanism working, not a broken test. Ask whether the key should be
#: registered or deleted before raising this number.
ORPHAN_BASELINE_MAX = 16


def test_the_baseline_may_only_shrink() -> None:
    """The ratchet. Growth requires editing the constant above, in review."""
    accepted = baselined_orphans()

    assert len(accepted) <= ORPHAN_BASELINE_MAX, (
        f"the orphan baseline grew to {len(accepted)} (max {ORPHAN_BASELINE_MAX}). "
        "Register the key in SECRET_CATALOG or delete it from the vault; raise "
        "ORPHAN_BASELINE_MAX only as a deliberate, reviewed decision."
    )


def test_every_baselined_orphan_carries_a_reason() -> None:
    """A bare key path is an accommodation; a reason is a follow-up.

    Enforced rather than trusted, because the cheapest way to defeat this whole
    mechanism is to paste a key in with no explanation of what would let it go.
    """
    for key, reason in baselined_orphans().items():
        assert reason.strip(), f"{key} has no reason in {ORPHAN_BASELINE_PATH.name}"
        assert len(reason.strip()) > 30, (
            f"{key}'s reason is too short to say what has to be true before the key "
            f"can go: {reason!r}"
        )


def test_an_unbaselined_orphan_is_reported() -> None:
    """The enforcement, observed failing. Fabricated vault, no SOPS, no decryption.

    lesson-306 exactly: without this, "the audit now fails on new orphans" is a
    claim about code nobody has watched refuse anything.
    """
    vault = {"apps": {"platform": {"api": {"totally_new_thing": "x"}}}}

    assert unbaselined_orphans(vault) == ["apps.platform.api.totally_new_thing"]


def test_a_baselined_orphan_is_not_reported() -> None:
    """The control. Without it the test above passes for a function that flags
    everything, which would fail the audit permanently and get the guard removed."""
    known = next(iter(baselined_orphans()))
    parts = known.split(".")

    vault: dict = {}
    node = vault
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = "x"

    assert unbaselined_orphans(vault) == []


def test_a_missing_baseline_raises_rather_than_permitting_everything() -> None:
    """A guard that cannot read its own data must not report success.

    Returning `{}` on a missing file would be the friendly choice and the wrong
    one twice over: every frozen orphan becomes a fresh failure, and — the part
    that matters — a moved or renamed file would make the ratchet silently
    permissive rather than loudly broken.
    """
    import toolkit.features.secrets_manager as sm

    original = sm.ORPHAN_BASELINE_PATH
    try:
        sm.ORPHAN_BASELINE_PATH = original.parent / "does-not-exist.yaml"
        with pytest.raises(FileNotFoundError, match="not optional"):
            sm.baselined_orphans()
    finally:
        sm.ORPHAN_BASELINE_PATH = original


def test_the_registered_superadmin_hash_is_no_longer_an_orphan() -> None:
    """The key that exposed the gap now has an owner rather than a baseline line.

    It is registered in SECRET_CATALOG with `envs=("prod",)` — the narrow form,
    because `envs` is the audit dimension (ANSIBLE-033) and declaring all three
    would report a gap in dev and staging for a key never written there.
    """
    from toolkit.features.secrets_manager import SECRET_CATALOG

    key = "apps.services.security.authelia.users_manu_password_hash"
    spec = next((s for s in SECRET_CATALOG if s.key_path == key), None)

    assert spec is not None, f"{key} must be registered, not baselined"
    assert spec.envs == ("prod",)
    assert key not in baselined_orphans()
