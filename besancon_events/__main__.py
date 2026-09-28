"""Point d'entrée : python -m besancon_events [--dry-run] [--config config.yaml]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import discord, filters
from .dates import PARIS
from .models import Event
from .sources import ai, feeds, jsonld, openagenda
from .state import State

log = logging.getLogger("besancon_events")


def collect(sources: dict, state: State, now: datetime) -> tuple[list[Event], set[str]]:
    """Interroge toutes les sources ; retourne les événements et les sources ayant répondu."""
    events: list[Event] = []
    ok: set[str] = set()
    for name, cfg in sources.items():
        if not cfg.get("enabled", True):
            continue
        kind = cfg["type"]
        try:
            if kind == "openagenda":
                found = openagenda.fetch(cfg, name, now)
            elif kind == "jsonld":
                found = jsonld.fetch(cfg, name, state.urls)
            elif kind == "ical":
                found = feeds.fetch_ical(cfg, name)
            elif kind == "rss":
                found = feeds.fetch_rss(cfg, name)
            elif kind == "ai":
                if not ai.available():
                    log.info("[%s] ignorée : ANTHROPIC_API_KEY non définie", name)
                    continue
                found, hashes = ai.fetch(cfg, name, state.page_hashes, now)
                state.page_hashes.update(hashes)
            else:
                log.error("[%s] type de source inconnu : %s", name, kind)
                continue
        except Exception as exc:  # une source en panne ne doit pas bloquer les autres
            log.error("[%s] échec : %s", name, exc)
            continue
        log.info("[%s] %d événements récupérés", name, len(found))
        events.extend(found)
        if found:
            ok.add(name)
    return events, ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agrégateur d'événements Besançon → Discord")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--state", default="state/seen.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="affiche les nouveautés sans rien envoyer ni enregistrer")
    parser.add_argument("--no-seed", action="store_true",
                        help="pour une source nouvelle, tout envoyer (sinon : mémorisation silencieuse)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    config = yaml.safe_load(Path(args.config).read_text())
    state = State(Path(args.state))
    now = datetime.now(PARIS)
    today = now.date()

    collected, ok_sources = collect(config["sources"], state, now)
    events = state.pending + collected
    # Mémorise les pages de détail visitées pour ne pas les re-télécharger
    for ev in events:
        if ev.url:
            state.urls.setdefault(ev.url, today.isoformat())

    events = filters.dedupe(filters.apply(events, config.get("filters", {}), now))
    new = [ev for ev in events if not state.is_seen(ev)]
    new.sort(key=lambda e: e.start or now)
    log.info("%d événements à venir, dont %d nouveaux", len(events), len(new))

    if args.dry_run:
        for ev in new:
            print(f"- [{ev.source}] {discord.format_when(ev)} | {ev.title} | {ev.location} | {ev.url}")
        return 0

    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        log.error("Variable d'environnement DISCORD_WEBHOOK_URL manquante")
        return 1

    # Source jamais vue (premier lancement ou ajout dans la config) : on mémorise
    # ses événements existants sans les envoyer, pour ne pas inonder le salon.
    new_sources = ok_sources - state.sources
    if new_sources and not args.no_seed:
        seeded = [ev for ev in new if ev.source in new_sources]
        for ev in seeded:
            state.mark(ev, today)
        new = [ev for ev in new if ev.source not in new_sources]
        discord.send_text(
            webhook,
            f"👋 Source(s) initialisée(s) : {', '.join(sorted(new_sources))} — "
            f"{len(seeded)} événements à venir déjà en mémoire. "
            "Seules les nouveautés seront annoncées désormais.",
        )
        log.info("Initialisation de %s : %d événements mémorisés", new_sources, len(seeded))
    state.sources |= ok_sources

    max_per_run = config.get("max_notifications_per_run", 40)
    to_send, state.pending = new[:max_per_run], new[max_per_run:]
    if state.pending:
        log.info("%d nouveautés reportées au prochain passage", len(state.pending))

    try:
        sent = discord.send_events(webhook, to_send, on_sent=lambda ev: state.mark(ev, today))
        log.info("%d notifications envoyées", sent)
    finally:
        state.prune(today)
        state.save()  # même en cas d'erreur, on garde la trace de ce qui est parti
    return 0


if __name__ == "__main__":
    sys.exit(main())
