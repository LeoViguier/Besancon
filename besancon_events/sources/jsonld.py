"""Extraction des données structurées schema.org/Event (JSON-LD).

Beaucoup de sites d'agenda (salles de concert, billetteries, offices de
tourisme) embarquent ces données pour Google : c'est la façon la plus fiable
de parser un site sans IA. Si la page liste ne contient pas d'Event, on peut
suivre les liens vers les pages de détail (`follow_links`).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import parse_date
from ..http import get
from ..models import Event

log = logging.getLogger(__name__)


def _is_event_type(t) -> bool:
    types = t if isinstance(t, list) else [t]
    return any(
        isinstance(x, str) and (x.endswith("Event") or x == "Festival") for x in types
    )


def _walk(node):
    """Parcourt récursivement le JSON-LD (@graph, ItemList, listes…)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        if _is_event_type(node.get("@type")):
            yield node
        for key in ("@graph", "itemListElement", "item", "subEvent"):
            if key in node:
                yield from _walk(node[key])


def _text(value) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("@value") or ""
    return BeautifulSoup(str(value or ""), "html.parser").get_text(" ").strip()


def _location(loc) -> tuple[str, str]:
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if isinstance(loc, str):
        return loc, ""
    if not isinstance(loc, dict):
        return "", ""
    name = _text(loc.get("name"))
    addr = loc.get("address") or {}
    city = ""
    if isinstance(addr, dict):
        city = _text(addr.get("addressLocality"))
    elif isinstance(addr, str) and not name:
        name = addr
    if city and city.lower() not in name.lower():
        name = f"{name}, {city}" if name else city
    return name, city


def _image(img) -> str:
    if isinstance(img, list):
        img = img[0] if img else ""
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl") or ""
    return img if isinstance(img, str) else ""


def events_from_html(html: str, page_url: str, source_name: str) -> list[Event]:
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Certains sites laissent des retours à la ligne dans les chaînes
            try:
                data = json.loads(re.sub(r"[\r\n\t]+", " ", raw))
            except json.JSONDecodeError:
                continue
        for node in _walk(data):
            title = _text(node.get("name"))
            if not title:
                continue
            place, city = _location(node.get("location"))
            url = node.get("url") or node.get("@id") or page_url
            if isinstance(url, list):
                url = url[0]
            events.append(
                Event(
                    title=title,
                    url=urljoin(page_url, str(url)),
                    source=source_name,
                    start=parse_date(node.get("startDate")),
                    end=parse_date(node.get("endDate")),
                    location=place,
                    city=city,
                    description=_text(node.get("description")),
                    image=urljoin(page_url, _image(node.get("image"))) if node.get("image") else "",
                )
            )
    return events


def fetch(cfg: dict, source_name: str, visited: dict[str, str] | None = None) -> list[Event]:
    """`visited` (url -> date) est mis à jour avec les fiches consultées, pour ne
    pas les re-télécharger aux passages suivants."""
    visited = {} if visited is None else visited
    events: list[Event] = []
    for page_url in cfg["urls"]:
        html = get(page_url).text
        found = events_from_html(html, page_url, source_name)
        events.extend(found)

        pattern = cfg.get("follow_links")
        if not pattern:
            continue
        # Pages de détail : on ne visite que les nouvelles (pas déjà vues)
        soup = BeautifulSoup(html, "html.parser")
        regex = re.compile(pattern)
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(page_url, a["href"]).split("#")[0]
            if regex.search(href) and href not in links and href not in visited:
                links.append(href)
        for href in links[: cfg.get("max_follow", 30)]:
            visited[href] = date.today().isoformat()
            try:
                detail = events_from_html(get(href).text, href, source_name)
            except Exception as exc:  # une page cassée ne doit pas bloquer les autres
                log.warning("[%s] %s : %s", source_name, href, exc)
                continue
            if not detail:
                log.debug("[%s] aucun JSON-LD Event sur %s", source_name, href)
            for ev in detail:
                ev.url = href  # l'URL de la page est plus fiable que celle du JSON-LD
            events.extend(detail)
    return events
