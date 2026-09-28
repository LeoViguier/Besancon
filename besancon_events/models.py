"""Modèle commun à toutes les sources."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .dates import PARIS


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation : sert à dédoublonner entre sources."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@dataclass
class Event:
    title: str
    url: str
    source: str
    start: datetime | None = None
    end: datetime | None = None
    location: str = ""
    city: str = ""
    description: str = ""
    image: str = ""
    tags: list[str] = field(default_factory=list)
    # Identifiant stable fourni par la source (uid OpenAgenda, UID iCal…)
    source_id: str = ""

    @property
    def key(self) -> str:
        """Clé de déduplication : même titre + même jour de début = même événement,
        même s'il est publié par plusieurs sources."""
        day = self.start.astimezone(PARIS).date().isoformat() if self.start else ""
        raw = f"{normalize(self.title)}|{day}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat() if self.start else None
        d["end"] = self.end.isoformat() if self.end else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        d = dict(d)
        d["start"] = datetime.fromisoformat(d["start"]) if d.get("start") else None
        d["end"] = datetime.fromisoformat(d["end"]) if d.get("end") else None
        return cls(**d)
