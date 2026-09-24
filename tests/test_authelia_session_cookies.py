"""#1805: no two Authelia instances may share a session cookie that one browser sends to both.

A browser sends a cookie scoped to `Domain=kubelab.live` to every host under it,
`*.staging.kubelab.live` included. When prod and staging both named their cookie
`authelia_session`, a browser holding a prod session sent staging two cookies
with that name. Staging Authelia read prod's, found no such session in its own
store, and answered `<anonymous>` to a user it had just logged in (measured
2026-09-24, Loki `{container="authelia"}`: a successful first factor followed,
the same second, by a 302 back to the portal). Nothing errors, so it reads as a
wrong password or a broken redirect.

Static, no cluster: it reads the Authelia config every environment loads.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent

#: One Authelia configuration per environment: base is staging, the prod overlay
#: ships its own file. Globbed rather than listed, so a new overlay is judged by
#: the rule without anyone remembering to add it here.
CONFIGS = sorted(REPO.glob("infra/k8s/**/authelia-config/configuration.yml"))


def _cookies() -> list[tuple[str, str, str]]:
    """(config, cookie name, cookie domain) for every session cookie declared."""
    found = []
    for path in CONFIGS:
        session = yaml.safe_load(path.read_text())["session"]
        for cookie in session.get("cookies") or []:
            found.append((str(path.relative_to(REPO)), cookie.get("name") or session["name"], cookie["domain"]))
    return found


def _covers(parent: str, child: str) -> bool:
    """Whether a cookie scoped to PARENT is also sent to hosts under CHILD."""
    return child == parent or child.endswith("." + parent)


def test_every_environment_is_read() -> None:
    """Guards the guard: an empty glob would pass the check below vacuously."""
    assert len({config for config, _, _ in _cookies()}) >= 2, CONFIGS


def test_no_browser_receives_two_session_cookies_with_one_name() -> None:
    clashes = [
        (a, b)
        for a, b in combinations(_cookies(), 2)
        if a[0] != b[0] and a[1] == b[1] and (_covers(a[2], b[2]) or _covers(b[2], a[2]))
    ]
    assert not clashes, (
        f"these Authelia instances share a session cookie name on overlapping domains: {clashes}. "
        "A browser holding one session sends both cookies, and the other instance reads the wrong one "
        "and treats a logged-in user as anonymous. Give each environment its own `session.name`."
    )
