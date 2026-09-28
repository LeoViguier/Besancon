"""OpenAgenda via le jeu de données public d'Opendatasoft (sans clé d'API).

Ce jeu agrège tous les agendas OpenAgenda publics de France : mairies,
médiathèques, musées, offices de tourisme, festivals… On le filtre par zone
géographique et on ne récupère que ce qui a été créé/modifié récemment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from ..dates import PARIS, parse_date
from ..http import get
from ..models import Event

log = logging.getLogger(__name__)

API = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "evenements-publics-openagenda/records"
)
PAGE_SIZE = 100  # maximum autorisé par l'API
MAX_OFFSET = 10_000  # offset + limit ne peut pas dépasser 10 000


def build_where(cfg: dict, now: datetime) -> str:
    """Construit la clause ODSQL à partir de la configuration de la source."""
    zones = []
    for region in cfg.get("regions", []):
        zones.append(f'location_region="{region}"')
    for dept in cfg.get("departments", []):
        zones.append(f'location_department="{dept}"')
    for city in cfg.get("cities", []):
        zones.append(f'location_city="{city}"')
    if cfg.get("around"):
        a = cfg["around"]
        zones.append(
            f"within_distance(location_coordinates, "
            f"geom'POINT({a['lon']} {a['lat']})', {a['radius_km']}km)"
        )
    if not zones:
        raise ValueError("La source openagenda doit définir au moins une zone")

    since = (now - timedelta(days=cfg.get("updated_within_days", 7))).date()
    clauses = [
        "(" + " or ".join(zones) + ")",
        f"lastdate_end >= date'{now.date().isoformat()}'",
        f"updatedat >= date'{since.isoformat()}'",
    ]
    for agenda in cfg.get("exclude_agendas", []):
        clauses.append(f'not originagenda_title like "*{agenda}*"')
    return " and ".join(clauses)


def to_event(rec: dict, source_name: str) -> Event:
    city = rec.get("location_city") or ""
    place = ", ".join(p for p in [rec.get("location_name"), city] if p)
    tags = list(rec.get("keywords_fr") or [])
    if rec.get("originagenda_title"):
        tags.append(rec["originagenda_title"])
    return Event(
        title=(rec.get("title_fr") or "").strip(),
        url=rec.get("canonicalurl") or "",
        source=source_name,
        start=parse_date(rec.get("firstdate_begin")),
        end=parse_date(rec.get("lastdate_end")),
        location=place,
        city=city,
        description=(rec.get("description_fr") or "").strip(),
        image=rec.get("image") or rec.get("thumbnail") or "",
        tags=tags,
        source_id=f"openagenda:{rec.get('uid')}",
    )


def fetch(cfg: dict, source_name: str, now: datetime | None = None) -> list[Event]:
    now = now or datetime.now(PARIS)
    where = build_where(cfg, now)
    max_records = min(cfg.get("max_records", 2000), MAX_OFFSET)
    log.debug("ODSQL where: %s", where)

    events: list[Event] = []
    offset = 0
    while offset < max_records:
        resp = get(
            API,
            params={
                "where": where,
                "order_by": "updatedat desc",
                "limit": PAGE_SIZE,
                "offset": offset,
            },
        )
        data = resp.json()
        results = data.get("results", [])
        events.extend(to_event(r, source_name) for r in results)
        offset += PAGE_SIZE
        if len(results) < PAGE_SIZE or offset >= data.get("total_count", 0):
            break
    return events
