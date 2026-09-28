import json
from datetime import datetime

import pytest
import yaml

from besancon_events import __main__ as app
from besancon_events import discord, filters
from besancon_events.dates import PARIS, parse_date
from besancon_events.models import Event
from besancon_events.sources import ai, jsonld, openagenda

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=PARIS)


def ev(title, start="2026-10-10T20:30:00+02:00", **kw):
    return Event(title=title, url=kw.pop("url", f"https://x.fr/{title}"), source=kw.pop("source", "oa"),
                 start=parse_date(start), **kw)


# ── OpenAgenda ──────────────────────────────────────────────────────────────

OA_RECORD = {
    "uid": "85175870",
    "canonicalurl": "https://openagenda.com/x/events/parcours",
    "title_fr": "Parcours architecture du XXe siècle à Chamars",
    "description_fr": "Balade commentée.",
    "keywords_fr": None,
    "image": "https://img.openagenda.com/main/a.jpg",
    "firstdate_begin": "2026-10-05T15:00:00+00:00",
    "lastdate_end": "2026-10-05T17:00:00+00:00",
    "location_name": "Promenade Chamars",
    "location_city": "Besançon",
    "originagenda_title": "Mois de l'architecture",
}


def test_openagenda_where_clause():
    where = openagenda.build_where(
        {"departments": ["Doubs"], "around": {"lat": 47.2, "lon": 6.0, "radius_km": 40},
         "updated_within_days": 7, "exclude_agendas": ["France Travail"]},
        NOW,
    )
    assert '(location_department="Doubs" or within_distance(location_coordinates, ' \
           "geom'POINT(6.0 47.2)', 40km))" in where
    assert "lastdate_end >= date'2026-09-28'" in where
    assert "updatedat >= date'2026-09-21'" in where
    assert 'not originagenda_title like "*France Travail*"' in where


def test_openagenda_record_mapping():
    e = openagenda.to_event(OA_RECORD, "oa")
    assert e.title == "Parcours architecture du XXe siècle à Chamars"
    assert e.location == "Promenade Chamars, Besançon"
    assert e.start.astimezone(PARIS).hour == 17
    assert e.source_id == "openagenda:85175870"
    assert "Mois de l'architecture" in e.tags


def test_openagenda_pagination(monkeypatch):
    calls = []

    class Resp:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    def fake_get(url, params):
        calls.append(params["offset"])
        n = 100 if params["offset"] == 0 else 20
        return Resp({"total_count": 120, "results": [dict(OA_RECORD, uid=str(i)) for i in range(n)]})

    monkeypatch.setattr(openagenda, "get", fake_get)
    events = openagenda.fetch({"departments": ["Doubs"]}, "oa", NOW)
    assert calls == [0, 100]
    assert len(events) == 120


# ── JSON-LD ─────────────────────────────────────────────────────────────────

JSONLD_PAGE = """
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebSite", "name": "Site"},
  {"@type": "MusicEvent", "name": "Camille", "startDate": "2026-11-19T20:30",
   "url": "/agenda/camille/", "image": {"url": "/img/camille.jpg"},
   "location": {"@type": "Place", "name": "La Rodia",
                "address": {"@type": "PostalAddress", "addressLocality": "Besançon"}},
   "description": "<p>Concert &amp; chanson</p>"}
]}
</script>
<script type="application/ld+json">
{"@type": "ItemList", "itemListElement": [
  {"@type": "ListItem", "item": {"@type": ["Event"], "name": "Expo",
   "startDate": "2026-10-01", "endDate": "2026-12-01", "location": "Musée"}}
]}
</script>
<script type="application/ld+json">{ cassé </script>
</head></html>
"""


def test_jsonld_extraction():
    events = jsonld.events_from_html(JSONLD_PAGE, "https://larodia.com/programmation/", "rodia")
    assert [e.title for e in events] == ["Camille", "Expo"]
    camille = events[0]
    assert camille.url == "https://larodia.com/agenda/camille/"
    assert camille.image == "https://larodia.com/img/camille.jpg"
    assert camille.location == "La Rodia, Besançon"
    assert camille.description == "Concert & chanson"
    assert camille.start == datetime(2026, 11, 19, 20, 30, tzinfo=PARIS)
    assert events[1].location == "Musée"


def test_jsonld_follow_links_skips_visited(monkeypatch):
    listing = '<a href="/besancon/concerts/a-1_A">a</a><a href="/besancon/concerts/b-2_A">b</a><a href="/autre">x</a>'
    detail = ('<script type="application/ld+json">{"@type":"Event","name":"B",'
              '"startDate":"2026-10-10"}</script>')
    fetched = []

    class Resp:
        def __init__(self, text):
            self.text = text

    def fake_get(url):
        fetched.append(url)
        return Resp(listing if url.endswith("agenda/") else detail)

    monkeypatch.setattr(jsonld, "get", fake_get)
    visited = {"https://www.jds.fr/besancon/concerts/a-1_A": "2026-09-01"}
    events = jsonld.fetch(
        {"urls": ["https://www.jds.fr/besancon/agenda/"], "follow_links": r"jds\.fr/besancon/.+-\d+_A$"},
        "jds", visited,
    )
    assert fetched == ["https://www.jds.fr/besancon/agenda/", "https://www.jds.fr/besancon/concerts/b-2_A"]
    assert [e.url for e in events] == ["https://www.jds.fr/besancon/concerts/b-2_A"]
    assert "https://www.jds.fr/besancon/concerts/b-2_A" in visited


# ── Filtres ─────────────────────────────────────────────────────────────────

def test_filters():
    events = [
        ev("Concert Camille"),
        ev("Mardi de l'intérim - Rencontrez ADECCO"),
        ev("Job Dating 100 % féminin"),
        ev("Atelier", tags=["Mes événements France Travail"]),
        ev("Vieux truc", start="2026-09-01"),
        ev("Expo en cours", start="2026-09-01", end=parse_date("2026-12-01")),
        ev("Trop loin", start="2028-01-01"),
        ev("Sans date", start=None),
        ev("Concert CVS"),  # « cv » ne doit exclure que le mot entier
    ]
    cfg = {"exclude_keywords": ["interim", "job dating", "France Travail", "cv"], "max_days_ahead": 365}
    kept = [e.title for e in filters.apply(events, cfg, NOW)]
    assert kept == ["Concert Camille", "Expo en cours", "Sans date", "Concert CVS"]


def test_dedupe_across_sources():
    a = ev("Camille — Concert", start="2026-11-19T20:30:00+01:00")
    b = ev("camille concert", start="2026-11-19T19:30:00+00:00")  # même jour à Paris
    c = ev("Camille concert", start="2026-11-20T20:30:00+01:00")
    assert filters.dedupe([a, b, c]) == [a, c]


# ── Discord ─────────────────────────────────────────────────────────────────

def test_format_when():
    assert discord.format_when(ev("a", start="2026-10-10T20:30:00+02:00")) == "Sam. 10 oct. 2026 à 20h30"
    assert discord.format_when(ev("a", start="2026-10-10")) == "Sam. 10 oct. 2026"
    multi = ev("a", start="2026-10-01", end=parse_date("2026-12-01"))
    assert discord.format_when(multi) == "Du jeu. 1 oct. 2026 au mar. 1 déc. 2026"
    assert discord.format_when(ev("a", start=None)) == "Date non précisée"


def test_discord_batches_respect_limits():
    events = [ev(f"Evénement {i}", description="x" * 1000) for i in range(25)]
    batches = list(discord.batches(events))
    assert sum(len(b) for b in batches) == 25
    for b in batches:
        assert len(b) <= 10
        assert sum(discord._embed_size(e) for _, e in b) <= discord.MAX_CHARS_PER_MESSAGE
    embed = batches[0][0][1]
    assert len(embed["description"]) <= 350
    assert embed["url"].startswith("https://")


# ── IA ──────────────────────────────────────────────────────────────────────

def test_page_to_text_keeps_links():
    html = '<nav><script>x()</script></nav><h2><a href="/agenda/2l/">2L</a></h2><p>16 Oct 20:30</p>'
    text = ai.page_to_text(html, "https://larodia.com/programmation/")
    assert "2L <https://larodia.com/agenda/2l/>" in text
    assert "x()" not in text


def test_ai_source_skips_unchanged_pages(monkeypatch):
    class Resp:
        text = "<p>Concert 2L le 16 octobre</p>"

    monkeypatch.setattr(ai, "get", lambda url: Resp())
    calls = []

    def fake_extract(text, url, model, now):
        calls.append(url)
        return [{"title": "2L", "start": "2026-10-16T20:30", "end": None, "location": "La Rodia",
                 "city": "Besançon", "url": "/agenda/2l/", "description": "rap"}]

    monkeypatch.setattr(ai, "extract", fake_extract)
    cfg = {"urls": ["https://larodia.com/programmation/"]}
    events, hashes = ai.fetch(cfg, "rodia", {}, NOW)
    assert events[0].url == "https://larodia.com/agenda/2l/"
    assert events[0].start == datetime(2026, 10, 16, 20, 30, tzinfo=PARIS)
    events2, hashes2 = ai.fetch(cfg, "rodia", hashes, NOW)
    assert events2 == [] and hashes2 == {} and len(calls) == 1


# ── Bout en bout ────────────────────────────────────────────────────────────

@pytest.fixture
def setup_run(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "max_notifications_per_run": 12,
        "filters": {"exclude_keywords": ["recrutement"]},
        "sources": {"oa": {"type": "openagenda", "departments": ["Doubs"]}},
    }))
    state = tmp_path / "state" / "seen.json"
    found: list[Event] = []
    posts: list[dict] = []
    monkeypatch.setattr(app.openagenda, "fetch", lambda cfg, name, now: list(found))
    monkeypatch.setattr(app.discord, "post", lambda url, payload: posts.append(payload))
    monkeypatch.setattr(app.discord.time, "sleep", lambda s: None)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    args = ["--config", str(config), "--state", str(state)]
    return args, state, found, posts


def test_end_to_end(setup_run):
    args, state, found, posts = setup_run

    # 1er passage : mémorisation silencieuse + message d'accueil
    found[:] = [ev("Ancien concert", start="2027-01-10"), ev("Recrutement BTP", start="2027-01-10")]
    assert app.main(args) == 0
    assert len(posts) == 1 and "initialisée" in posts[0]["content"]
    assert "embeds" not in posts[0]

    # 2e passage : seules les nouveautés partent, plafonnées à 12
    found[:] = [ev("Ancien concert", start="2027-01-10")] + [
        ev(f"Nouveau {i:02d}", start=f"2027-02-{i + 1:02d}") for i in range(15)
    ]
    posts.clear()
    assert app.main(args) == 0
    titles = [e["title"] for p in posts for e in p["embeds"]]
    assert titles == [f"Nouveau {i:02d}" for i in range(12)]
    saved = json.loads(state.read_text())
    assert [p["title"] for p in saved["pending"]] == ["Nouveau 12", "Nouveau 13", "Nouveau 14"]

    # 3e passage : les reportés partent même si la source ne les renvoie plus
    found[:] = []
    posts.clear()
    assert app.main(args) == 0
    titles = [e["title"] for p in posts for e in p["embeds"]]
    assert titles == ["Nouveau 12", "Nouveau 13", "Nouveau 14"]

    # 4e passage : plus rien
    posts.clear()
    assert app.main(args) == 0
    assert posts == []


def test_failing_source_does_not_stop_run(setup_run, monkeypatch):
    args, state, found, posts = setup_run

    def boom(*a):
        raise RuntimeError("site en panne")

    monkeypatch.setattr(app.openagenda, "fetch", boom)
    assert app.main(args) == 0
    assert posts == []
    # La source en panne n'est pas considérée comme initialisée :
    # à son retour, son contenu existant sera mémorisé sans être envoyé.
    assert json.loads(state.read_text())["sources"] == []


def test_new_source_is_seeded_silently(setup_run, monkeypatch):
    args, state, found, posts = setup_run
    found[:] = [ev("Concert A", start="2027-01-10")]
    app.main(args)  # initialise « oa »

    rss_items = [Event(title=f"Actu {i}", url=f"https://r.fr/{i}", source="rss", start=None) for i in range(5)]
    monkeypatch.setattr(app.feeds, "fetch_rss", lambda cfg, name: list(rss_items))
    config = yaml.safe_load(open(args[1]))
    config["sources"]["rss"] = {"type": "rss", "urls": ["https://r.fr/feed"]}
    open(args[1], "w").write(yaml.safe_dump(config))

    found[:] = [ev("Concert A", start="2027-01-10"), ev("Concert B", start="2027-01-11")]
    posts.clear()
    app.main(args)
    embeds = [e["title"] for p in posts if "embeds" in p for e in p["embeds"]]
    assert embeds == ["Concert B"]  # la nouveauté de la source existante part
    assert any("rss" in p.get("content", "") for p in posts)  # la nouvelle source est mémorisée
