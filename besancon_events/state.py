"""Mémoire des événements déjà notifiés (fichier JSON versionné dans le dépôt)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .models import Event

RETENTION_DAYS = 400


class State:
    def __init__(self, path: Path):
        self.path = path
        data = json.loads(path.read_text()) if path.exists() else {}
        # identifiant -> date à laquelle on l'a vu pour la première fois
        self.seen: dict[str, str] = data.get("seen", {})
        self.urls: dict[str, str] = data.get("urls", {})
        self.page_hashes: dict[str, str] = data.get("page_hashes", {})
        # Sources déjà initialisées (leurs événements existants ont été mémorisés)
        self.sources: set[str] = set(data.get("sources", []))
        # Nouveautés pas encore envoyées (plafond par passage atteint)
        self.pending: list[Event] = [Event.from_dict(e) for e in data.get("pending", [])]

    def is_seen(self, ev: Event) -> bool:
        return ev.key in self.seen or (ev.source_id and ev.source_id in self.seen) or False

    def mark(self, ev: Event, today: date) -> None:
        stamp = today.isoformat()
        self.seen.setdefault(ev.key, stamp)
        if ev.source_id:
            self.seen.setdefault(ev.source_id, stamp)
        if ev.url:
            self.urls.setdefault(ev.url, stamp)

    def prune(self, today: date) -> None:
        limit = (today - timedelta(days=RETENTION_DAYS)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v >= limit}
        self.urls = {k: v for k, v in self.urls.items() if v >= limit}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seen": self.seen,
            "urls": self.urls,
            "page_hashes": self.page_hashes,
            "pending": [e.to_dict() for e in self.pending],
            "sources": sorted(self.sources),
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
