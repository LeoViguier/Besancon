"""Filtrage : événements passés, trop lointains, ou jugés sans intérêt."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .models import Event, normalize


def _keyword_regex(keywords: list[str]) -> re.Pattern | None:
    words = [normalize(k) for k in keywords if normalize(k)]
    if not words:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b")


def is_excluded(ev: Event, exclude: re.Pattern | None) -> bool:
    if exclude is None:
        return False
    haystack = normalize(" ".join([ev.title, *ev.tags]))
    return bool(exclude.search(haystack))


def apply(events: list[Event], cfg: dict, now: datetime) -> list[Event]:
    exclude = _keyword_regex(cfg.get("exclude_keywords", []))
    horizon = now + timedelta(days=cfg.get("max_days_ahead", 365))
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    kept = []
    for ev in events:
        if not ev.title:
            continue
        last = ev.end or ev.start
        if last and last < today:
            continue  # déjà terminé
        if ev.start and ev.start > horizon:
            continue
        if is_excluded(ev, exclude):
            continue
        kept.append(ev)
    return kept


def dedupe(events: list[Event]) -> list[Event]:
    """Supprime les doublons d'un même passage (même événement sur plusieurs sources)."""
    seen: set[str] = set()
    out = []
    for ev in events:
        ids = {ev.key} | ({ev.source_id} if ev.source_id else set())
        if ids & seen:
            continue
        seen |= ids
        out.append(ev)
    return out
