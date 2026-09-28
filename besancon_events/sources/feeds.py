"""Flux iCal (.ics) et RSS/Atom."""

from __future__ import annotations

from datetime import datetime

import feedparser
from bs4 import BeautifulSoup
from icalendar import Calendar

from ..dates import PARIS, parse_date
from ..http import get
from ..models import Event


def fetch_ical(cfg: dict, source_name: str) -> list[Event]:
    events = []
    for url in cfg["urls"]:
        cal = Calendar.from_ical(get(url).content)
        for comp in cal.walk("VEVENT"):
            start = comp.get("DTSTART")
            end = comp.get("DTEND")
            events.append(
                Event(
                    title=str(comp.get("SUMMARY", "")).strip(),
                    url=str(comp.get("URL", "") or url),
                    source=source_name,
                    start=parse_date(start.dt) if start else None,
                    end=parse_date(end.dt) if end else None,
                    location=str(comp.get("LOCATION", "")),
                    description=str(comp.get("DESCRIPTION", "")).strip(),
                    source_id=f"ical:{comp.get('UID', '')}" if comp.get("UID") else "",
                )
            )
    return events


def fetch_rss(cfg: dict, source_name: str) -> list[Event]:
    """Un flux RSS donne rarement la date de l'événement : on l'envoie quand
    même (date de publication inconnue), utile pour les actus « sorties »."""
    events = []
    for url in cfg["urls"]:
        feed = feedparser.parse(get(url).content)
        for entry in feed.entries:
            published = None
            if entry.get("published_parsed"):
                published = datetime(*entry.published_parsed[:6], tzinfo=PARIS)
            summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ")
            events.append(
                Event(
                    title=entry.get("title", "").strip(),
                    url=entry.get("link", url),
                    source=source_name,
                    description=summary.strip(),
                    source_id=f"rss:{entry.get('id') or entry.get('link')}",
                    tags=["actu"] + ([published.strftime("%d/%m/%Y")] if published else []),
                )
            )
    return events
