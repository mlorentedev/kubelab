"""APP-CONFIG-018 (#2088): the sale digest is a Spanish email the owner can read at a glance.

The first version arrived as English plain text: a wall of `name N` pairs. This runs the REAL
`jsCode` of the "Write the digest" node, committed in the workflow JSON, on fixture answers shaped
like the three upstream nodes' output, and asserts on what the email node CONSUMES: the `subject`,
`html` and `text` fields the node maps, not that the JSON parses.

Two things the fixtures take from the real system rather than assuming:
- Analytics Engine returns `n` as a STRING (`SUM(_sample_interval)` over FORMAT JSON), so every fixture
  row does too. A node that adds strings concatenates them and still prints a number-looking subject.
- The event ids reach the dataset from a PUBLIC endpoint, so the HTML must escape them. The
  endpoint slugs them today; the digest does not rely on that.

`$now` is a stand-in that formats through Intl and REFUSES any format string it was not written for,
so a changed token fails here instead of silently being formatted by the stand-in. It formats in the
locale the node asked for: a node that forgets `setLocale('es')` gets an English date and fails the
subject test. The same code was also run once against the real Luxon 3.7.2 that n8n ships.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
from typing import Any

import pytest

from tests.n8n_code_node import node_js

WORKFLOW = "sale-metrics-daily-digest.json"
WORKFLOW_PATH = pathlib.Path(__file__).resolve().parents[1] / "infra" / "n8n" / "workflows" / WORKFLOW
DIGEST_NODE = "Write the digest"
EMAIL_NODE = "Email the digest"
SITE = "https://leaving-denver.pages.dev"

#: Wednesday 2026-10-07 08:00 in Denver (UTC-6 in daylight time).
NOW_ISO = "2026-10-07T14:00:00.000Z"

FAKE_NOW = """
const FORMATS = {
  'ccc d LLL': (p) => `${p.weekday} ${p.day} ${p.month}`,
  "cccc d 'de' LLLL": (p) => `${p.weekday} ${p.day} de ${p.month}`,
};
const OPTIONS = {
  'ccc d LLL': { weekday: 'short', day: 'numeric', month: 'short' },
  "cccc d 'de' LLLL": { weekday: 'long', day: 'numeric', month: 'long' },
};
class FakeNow {
  constructor(ms, zone = 'UTC', locale = 'en-US') { this.ms = ms; this.zone = zone; this.locale = locale; }
  toUTC() { return new FakeNow(this.ms, 'UTC', this.locale); }
  minus({ hours }) { return new FakeNow(this.ms - hours * 3600e3, this.zone, this.locale); }
  toISO() { return new Date(this.ms).toISOString(); }
  setZone(zone) { return new FakeNow(this.ms, zone, this.locale); }
  setLocale(locale) { return new FakeNow(this.ms, this.zone, locale); }
  toFormat(format) {
    if (!OPTIONS[format]) throw new Error(`the $now stand-in does not know the format ${format}`);
    const parts = Object.fromEntries(new Intl.DateTimeFormat(this.locale, { ...OPTIONS[format], timeZone: this.zone })
      .formatToParts(new Date(this.ms)).map((p) => [p.type, p.value]));
    return FORMATS[format](parts);
  }
}
const $now = new FakeNow(Date.parse(NOW_ISO));
""".replace("NOW_ISO", json.dumps(NOW_ISO))


def run_digest(nodes: dict[str, Any], js: str | None = None, prelude: str = FAKE_NOW) -> dict[str, Any]:
    """Run the Code node as n8n does: `$('<name>').first().json` reads each upstream answer."""
    js = js if js is not None else node_js(WORKFLOW, DIGEST_NODE)
    script = f"""
    const NODES = {json.dumps(nodes)};
    const $ = (name) => {{
      if (!(name in NODES)) throw new Error('the node was not run: ' + name);
      return {{ first: () => ({{ json: NODES[name] }}) }};
    }};
    {prelude}
    (async function () {{
      {js}
    }})().then(
      (out) => console.log(JSON.stringify(out.map((i) => i.json))),
      (err) => {{ console.error(err); process.exit(1); }},
    );
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    out = json.loads(proc.stdout.strip())
    assert len(out) == 1, "the digest is one email"
    return out[0]


def row(event: str, n: int, source: str = "", item: str = "", bundle: str = "") -> dict[str, str]:
    return {"event": event, "source": source, "item": item, "bundle": bundle, "n": str(n)}


def answer(*rows: dict[str, str]) -> dict[str, Any]:
    return {"data": list(rows)}


def web_answer(visits: int, views: int, referrers: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "data": {
            "viewer": {
                "accounts": [
                    {
                        "totals": [{"count": views, "sum": {"visits": visits}}],
                        "referrers": [{"count": n, "dimensions": {"refererHost": host}} for host, n in referrers],
                    }
                ]
            }
        }
    }


RECENT_ROWS = (
    row("visit", 9, source="flyer"),
    row("visit", 1, source="share"),
    row("view_item", 3, item="sofa-sleeper"),
    row("view_item", 2, item="air-mattress-twin-pump"),
    row("view_item", 2, item="dell-monitor-32"),
    row("view_item", 1, item="bar-stools"),
    row("text_tap", 1, source="flyer", item="sofa-sleeper"),
)
SALE_ROWS = (*RECENT_ROWS, row("view_item", 6, item="onn-43-4k-tv"), row("view_item", 5, item="convertible-desk"))


def nodes(recent: Any = None, sale: Any = None, web: Any = None) -> dict[str, Any]:
    return {
        "Events, last 24 h": answer(*RECENT_ROWS) if recent is None else recent,
        "Events, whole sale": answer(*SALE_ROWS) if sale is None else sale,
        "Web Analytics, last 24 h": (
            web_answer(14, 41, [("", 10), ("facebook.com", 2), ("l.instagram.com", 1)]) if web is None else web
        ),
    }


def visible(html: str) -> str:
    """What a reader sees: tags dropped, entities left alone, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


@pytest.fixture(scope="module")
def digest() -> dict[str, Any]:
    return run_digest(nodes())


# -- the email the owner reads ------------------------------------------------------------


class TestSubject:
    def test_it_says_the_numbers_in_spanish(self, digest: dict[str, Any]) -> None:
        assert digest["subject"] == "Venta · mié 7 oct — 14 visitas, 8 fichas, 1 mensaje"

    def test_the_date_is_denver_s_even_when_utc_is_already_the_next_day(self) -> None:
        """A run from the n8n UI at 22:00 in Denver is 04:00 the next day in UTC."""
        late = FAKE_NOW.replace(json.dumps(NOW_ISO), json.dumps("2026-10-08T04:00:00.000Z"))
        assert late != FAKE_NOW
        email = run_digest(nodes(), prelude=late)
        assert email["subject"].startswith("Venta · mié 7 oct — ")
        assert "Miércoles 7 de octubre" in visible(email["html"])

    def test_singular_and_plural_agree_with_the_count(self) -> None:
        one = run_digest(
            nodes(
                recent=answer(row("view_item", 1, item="sofa"), row("text_tap", 1, item="sofa")),
                web=web_answer(1, 1, []),
            )
        )
        assert one["subject"] == "Venta · mié 7 oct — 1 visita, 1 ficha, 1 mensaje"
        none = run_digest(nodes(recent=answer(), web=web_answer(0, 0, [])))
        assert none["subject"] == "Venta · mié 7 oct — 0 visitas, 0 fichas, 0 mensajes"

    def test_visits_fall_back_to_the_tracked_links_when_web_analytics_fails(self) -> None:
        subject = run_digest(nodes(web={"errors": [{"message": "denied"}]}))["subject"]
        assert subject == "Venta · mié 7 oct — 10 visitas, 8 fichas, 1 mensaje (datos incompletos)"

    def test_a_failed_event_query_leaves_out_what_it_would_have_counted(self) -> None:
        subject = run_digest(nodes(recent={"success": False, "errors": [{"code": 10000}]}))["subject"]
        assert subject == "Venta · mié 7 oct — 14 visitas (datos incompletos)"

    def test_everything_failing_still_gives_a_subject(self) -> None:
        failed = {"success": False}
        subject = run_digest(nodes(recent=failed, sale=failed, web={"error": "timeout"}))["subject"]
        assert subject == "Venta · mié 7 oct — sin datos"


class TestEmailNodeConsumesTheOutput:
    def test_html_and_text_are_mapped_and_the_format_is_both(self, digest: dict[str, Any]) -> None:
        """The node's expressions are evaluated against what the code node returned: a field the
        code node does not emit, or a format the node does not ask for, reaches nobody."""
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        params = next(n for n in workflow["nodes"] if n["name"] == EMAIL_NODE)["parameters"]
        assert params["emailFormat"] == "both"
        assert set(digest) == {"subject", "html", "text"}
        for field in ("subject", "html", "text"):
            match = re.fullmatch(r"=\{\{ \$json\.(\w+) \}\}", params[field])
            assert match, f"{field} is not a plain `$json.<key>` mapping: {params[field]!r}"
            assert digest[match.group(1)].strip(), f"{field} maps to an empty value"

    def test_the_digest_reads_only_nodes_that_exist_upstream_of_it(self, digest: dict[str, Any]) -> None:
        """`$('<name>')` on a renamed or missing node fails only when n8n runs it, at 08:00. The
        stand-in `$` throws on a name it was not given, so the `digest` fixture running at all proves
        the code reads nothing outside `nodes()`; here those names must be real nodes, each one read."""
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        upstream = {n["name"] for n in workflow["nodes"]} - {DIGEST_NODE, EMAIL_NODE}
        assert set(nodes()) <= upstream
        for name in nodes():
            without = {k: v for k, v in nodes().items() if k != name}
            with pytest.raises(subprocess.CalledProcessError):
                run_digest(without)


class TestHeaderAndKpis:
    def test_header_has_the_title_and_the_long_date(self, digest: dict[str, Any]) -> None:
        assert "Resumen de la venta" in visible(digest["html"])
        assert "Miércoles 7 de octubre" in visible(digest["html"])

    def test_the_three_tiles_carry_their_numbers_in_order(self, digest: dict[str, Any]) -> None:
        # whole sale: 8 + 6 + 5 = 19 views, 1 tap
        assert "Visitas web 14 41 páginas vistas Fichas abiertas 8 total: 19 Mensajes 1 total: 1" in visible(
            digest["html"]
        )

    def test_the_messages_tile_stands_out_and_the_others_do_not(self, digest: dict[str, Any]) -> None:
        html = digest["html"]
        accents = re.findall(r"#0f766e", html)
        assert accents, "no accent colour"
        tile = re.search(r"<td[^>]*>(?:(?!</td>).)*Mensajes(?:(?!</td>).)*</td>", html, re.S)
        assert tile and "#0f766e" in tile.group(0), "the Mensajes tile is not the accented one"
        visits_tile = re.search(r"<td[^>]*>(?:(?!</td>).)*Visitas web(?:(?!</td>).)*</td>", html, re.S)
        assert visits_tile and "#0f766e" not in visits_tile.group(0)

    def test_the_text_fallback_says_the_same(self, digest: dict[str, Any]) -> None:
        text = digest["text"]
        assert "Visitas web: 14 (41 páginas vistas)" in text
        assert "Fichas abiertas: 8 (total: 19)" in text
        assert "Mensajes: 1 (total: 1)" in text
        assert "Miércoles 7 de octubre" in text


class TestTopItems:
    def test_ordered_by_views_then_messages_and_capped_at_five(self) -> None:
        rows = [row("view_item", 10 - i, item=f"item-{i}") for i in range(7)]
        out = run_digest(nodes(recent=answer(*rows)))
        names = re.findall(r"Item \d", out["text"])
        assert names == ["Item 0", "Item 1", "Item 2", "Item 3", "Item 4"]

    def test_views_and_messages_per_item_and_a_tie_broken_by_messages(self, digest: dict[str, Any]) -> None:
        text = digest["text"]
        lines = [line for line in text.splitlines() if re.match(r"\s+- ", line)]
        assert lines[0].startswith("  - Sofa sleeper: 3 vistas, 1 mensaje")
        assert lines[1].startswith("  - Air mattress twin pump: 2 vistas")
        assert lines[2].startswith("  - Dell monitor 32: 2 vistas")
        tie = run_digest(
            nodes(
                recent=answer(
                    row("view_item", 2, item="aaa"), row("view_item", 2, item="zzz"), row("text_tap", 1, item="zzz")
                )
            )
        )
        assert tie["text"].index("Zzz") < tie["text"].index("Aaa")

    def test_ids_are_humanized_and_link_to_the_item_page(self, digest: dict[str, Any]) -> None:
        assert f'href="{SITE}/i/air-mattress-twin-pump/"' in digest["html"]
        assert "Air mattress twin pump" in visible(digest["html"])
        assert "air-mattress-twin-pump" not in visible(digest["html"])

    def test_a_bundle_tap_is_its_own_row(self) -> None:
        out = run_digest(
            nodes(
                recent=answer(row("view_item", 2, item="sofa-sleeper"), row("text_tap", 2, bundle="living-room-pack"))
            )
        )
        assert "Pack: Living room pack" in visible(out["html"])
        assert "Pack: Living room pack: 2 mensajes" in out["text"]
        assert f"{SITE}/i/living-room-pack/" not in out["html"], "a bundle is not an item page"

    def test_an_item_with_a_message_and_no_view_today_is_not_dropped(self) -> None:
        out = run_digest(nodes(recent=answer(row("view_item", 4, item="a"), row("text_tap", 1, item="late-lead"))))
        assert "Late lead: 0 vistas, 1 mensaje" in out["text"]

    def test_nobody_opened_a_listing(self) -> None:
        out = run_digest(nodes(recent=answer(row("visit", 2, source="flyer"))))
        assert "Nadie abrió fichas ayer." in visible(out["html"])
        assert "Nadie abrió fichas ayer." in out["text"]


class TestSources:
    def test_tracked_sources_are_labelled_and_sorted(self) -> None:
        recent = answer(
            row("visit", 1, source="activebuilding"),
            row("visit", 7, source="carscom"),
            row("visit", 3, source="offerup"),
            row("visit", 3, source="nextdoor"),
            row("visit", 2, source="other"),
            row("visit", 1, source="direct"),
            row("visit", 1, source="whatsapp"),
            row("visit", 1, source="craigslist"),
            row("visit", 1, source="instagram"),
        )
        out = run_digest(nodes(recent=recent))
        line = next(line for line in out["text"].splitlines() if "Cars.com" in line)
        assert "Cars.com 7 · Nextdoor 3 · OfferUp 3 · Otros 2 · ActiveBuilding 1 · Craigslist 1" in line
        assert "Directo 1" in line and "Instagram 1" in line and "WhatsApp 1" in line

    def test_flyer_facebook_and_share_labels(self) -> None:
        out = run_digest(
            nodes(
                recent=answer(
                    row("visit", 3, source="flyer"), row("visit", 2, source="facebook"), row("visit", 1, source="share")
                )
            )
        )
        assert "Flyer 3 · Facebook 2 · Compartido 1" in out["text"]

    def test_web_analytics_referrers_and_an_empty_host_reads_directo(self, digest: dict[str, Any]) -> None:
        assert "Directo 10 · facebook.com 2 · l.instagram.com 1" in digest["text"]
        assert "Directo 10 · facebook.com 2 · l.instagram.com 1" in visible(digest["html"])

    def test_no_tracked_visits_says_so_without_failing(self) -> None:
        out = run_digest(nodes(recent=answer(row("view_item", 1, item="a"))))
        assert "Sin visitas por enlace" in out["text"]
        assert "No disponible" not in out["text"]


class TestRepricing:
    def test_many_views_and_no_message_is_listed_with_the_hint(self, digest: dict[str, Any]) -> None:
        assert "Revisar precio" in visible(digest["html"])
        text = digest["text"]
        assert "Onn 43 4k tv: 6 vistas" in text
        assert "make reprice ID=onn-43-4k-tv PRICE=<usd>" in text
        assert "make reprice ID=convertible-desk PRICE=<usd>" in text
        assert text.index("Onn 43 4k tv") < text.index("Convertible desk"), "most viewed first"
        assert "make reprice ID=onn-43-4k-tv PRICE=&lt;usd&gt;" in digest["html"]

    def test_the_threshold_is_five_views(self) -> None:
        sale = answer(row("view_item", 4, item="four-views"), row("view_item", 5, item="five-views"))
        out = run_digest(nodes(sale=sale))
        assert "make reprice ID=five-views" in out["text"]
        assert "four-views" not in out["text"].split("Revisar precio")[1]

    def test_an_item_with_a_message_is_not_a_candidate(self, digest: dict[str, Any]) -> None:
        assert "make reprice ID=sofa-sleeper" not in digest["text"]
        sale = answer(row("view_item", 9, item="sofa"), row("text_tap", 1, item="sofa"))
        out = run_digest(nodes(sale=sale))
        assert "Revisar precio" not in out["text"]

    def test_the_section_is_omitted_when_there_are_none(self) -> None:
        out = run_digest(nodes(sale=answer(row("view_item", 3, item="a"))))
        assert "Revisar precio" not in out["text"]
        assert "Revisar precio" not in out["html"]
        assert "make reprice" not in out["html"]


class TestFooter:
    def test_whole_sale_totals_and_the_events_not_people_note(self, digest: dict[str, Any]) -> None:
        line = "Toda la venta: 10 visitas por enlace · 19 fichas · 1 mensaje. Se cuentan eventos, no personas."
        assert line in digest["text"]
        assert line in visible(digest["html"])


# -- failure handling ------------------------------------------------------------------------


class TestFailSoft:
    EVENTS_FAILED = {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}

    def test_a_failed_24h_events_query_is_named_in_its_sections_and_the_rest_survives(self) -> None:
        out = run_digest(nodes(recent=self.EVENTS_FAILED))
        text = out["text"]
        assert "No disponible: la consulta a Analytics Engine falló (ver la ejecución en n8n)" in text
        assert "Directo 10 · facebook.com 2" in text, "Web Analytics still reported"
        assert "Visitas web: 14" in text
        assert "Fichas abiertas: — (total: 19)" in text
        assert "make reprice ID=onn-43-4k-tv" in text, "the whole-sale section is independent"
        assert "No disponible" in visible(out["html"])

    def test_a_failed_whole_sale_query_names_the_repricing_section_and_the_footer(self) -> None:
        out = run_digest(nodes(sale=self.EVENTS_FAILED))
        text = out["text"]
        assert "Revisar precio" in text
        assert (
            text.split("Revisar precio")[1].lstrip().startswith("No disponible: la consulta a Analytics Engine falló")
        )
        assert "Toda la venta: no disponible." in text
        assert "Fichas abiertas: 8 (total: —)" in text
        assert "Sofa sleeper: 3 vistas" in text

    def test_a_web_analytics_error_hides_even_the_partial_data_beside_it(self) -> None:
        """GraphQL answers 200 with `errors`, sometimes beside partial data: those figures are not printed."""
        web = web_answer(777, 888, [("partial.example", 5)])
        web["errors"] = [{"message": "internal error"}]
        out = run_digest(nodes(web=web))
        for rendered in (out["text"], out["html"], out["subject"]):
            assert "777" not in rendered and "888" not in rendered and "partial.example" not in rendered
        assert "No disponible: la consulta a Web Analytics devolvió errores (ver la ejecución en n8n)" in out["text"]
        assert "Fichas abiertas: 8" in out["text"], "the event sections survive"

    def test_web_analytics_answering_with_no_data_points_at_the_site_tag_and_the_token(self) -> None:
        out = run_digest(nodes(web={"error": "401 unauthorized"}))
        reason = "la consulta a Web Analytics no devolvió datos (revisa el site tag y el token, ver el runbook)"
        assert f"No disponible: {reason}" in out["text"]
        assert "Visitas web: — (No disponible)" in out["text"]

    def test_a_site_with_no_page_views_is_zero_not_a_failure(self) -> None:
        web = {"data": {"viewer": {"accounts": [{"totals": [], "referrers": []}]}}}
        out = run_digest(nodes(web=web))
        assert "Visitas web: 0 (0 páginas vistas)" in out["text"]
        assert "No disponible: la consulta a Web" not in out["text"]
        assert "datos incompletos" not in out["subject"]

    def test_an_unreadable_count_is_zero_not_nan(self) -> None:
        out = run_digest(
            nodes(recent=answer({"event": "view_item", "source": "", "item": "x", "bundle": "", "n": "oops"}))
        )
        assert "NaN" not in out["text"] + out["html"] + out["subject"]


# -- the HTML is safe to send ------------------------------------------------------------------


HOSTILE_ITEM = "<script>alert(1)</script>"
HOSTILE_SOURCE = '"><img src=x onerror=alert(2)>'
HOSTILE_HOST = "evil.example/<b onmouseover=alert(3)>"
HOSTILE_BUNDLE = "<svg onload=alert(4)>"


@pytest.fixture(scope="module")
def hostile() -> dict[str, Any]:
    recent = answer(
        row("view_item", 6, item=HOSTILE_ITEM),
        row("visit", 2, source=HOSTILE_SOURCE),
        row("text_tap", 1, bundle=HOSTILE_BUNDLE),
    )
    sale = answer(row("view_item", 9, item=HOSTILE_ITEM))
    web = web_answer(3, 4, [(HOSTILE_HOST, 3)])
    return run_digest(nodes(recent=recent, sale=sale, web=web))


class TestHtmlSafety:
    def test_every_value_that_comes_from_data_is_escaped(self, hostile: dict[str, Any]) -> None:
        html = hostile["html"]
        for raw in ("<script", "<img", "<svg", "<b onmouseover", '"><img'):
            assert raw not in html, f"{raw!r} reached the HTML unescaped"
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&quot;&gt;&lt;img src=x onerror=alert(2)&gt;" in html
        assert "&lt;svg onload=alert(4)&gt;" in html
        assert "evil.example/&lt;b onmouseover=alert(3)&gt;" in html

    def test_an_id_in_a_link_is_percent_encoded_and_cannot_break_out_of_the_attribute(
        self, hostile: dict[str, Any]
    ) -> None:
        hrefs = re.findall(r'href="([^"]*)"', hostile["html"])
        assert hrefs, "no links rendered"
        for href in hrefs:
            assert href.startswith(SITE + "/i/") and href.endswith("/")
            assert not re.search(r"[<>\s]", href)
        assert f"{SITE}/i/%3Cscript%3Ealert(1)%3C%2Fscript%3E/" in hrefs

    def test_an_id_named_like_an_object_property_is_just_an_id(self) -> None:
        """`constructor` and `__proto__` are keys in the data, not lookups on the counting objects."""
        recent = answer(
            row("view_item", 4, item="constructor"),
            row("view_item", 3, item="__proto__"),
            row("visit", 2, source="constructor"),
            row("visit", 1, source="__proto__"),
        )
        out = run_digest(nodes(recent=recent))
        assert "Constructor: 4 vistas" in out["text"] and "Proto: 3 vistas" in out["text"]
        assert "Constructor 2 · Proto 1" in out["text"]
        assert "NaN" not in out["text"] and "function" not in out["text"]

    def test_the_subject_is_plain_text_with_nothing_from_the_data(self, hostile: dict[str, Any]) -> None:
        assert "<" not in hostile["subject"]

    def test_email_safe_markup_only(self, digest: dict[str, Any]) -> None:
        html = digest["html"]
        assert "max-width:560px" in html
        assert "<table" in html
        for forbidden in ("<img", "<link", "<style", "<script", "@import", "url(", "<iframe"):
            assert forbidden not in html, forbidden
        urls = set(re.findall(r"(?:href|src)=\"([^\"]+)\"", html))
        assert all(u.startswith(SITE + "/i/") for u in urls), urls
        assert not re.findall(r"https?://(?!leaving-denver\.pages\.dev/i/)[^\s\"'<]+", html), "an external reference"
        assert 'lang="es"' in html
