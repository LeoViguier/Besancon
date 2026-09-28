"""Envoi des notifications sur Discord via un webhook."""

from __future__ import annotations

import logging
import time
from datetime import datetime

import requests

from .dates import PARIS
from .models import Event

log = logging.getLogger(__name__)

EMBEDS_PER_MESSAGE = 10  # limite Discord
MAX_CHARS_PER_MESSAGE = 5500  # limite Discord : 6000 caractères d'embeds par message

JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
        "sept.", "oct.", "nov.", "déc."]

COLORS = [0x5865F2, 0x57F287, 0xFEE75C, 0xEB459E, 0xED4245, 0x3BA55C, 0xFAA61A]


def _fmt_day(dt: datetime) -> str:
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month - 1]} {dt.year}"


def _fmt_time(dt: datetime) -> str:
    return f"{dt.hour}h{dt.minute:02d}" if dt.minute else f"{dt.hour}h"


def format_when(ev: Event) -> str:
    if not ev.start:
        return "Date non précisée"
    start = ev.start.astimezone(PARIS)
    has_time = (start.hour, start.minute) != (0, 0)
    end = ev.end.astimezone(PARIS) if ev.end else None
    if end and end.date() != start.date():
        return f"Du {_fmt_day(start)} au {_fmt_day(end)}"
    text = _fmt_day(start).capitalize()
    if has_time:
        text += f" à {_fmt_time(start)}"
    return text


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_embed(ev: Event) -> dict:
    embed = {
        "title": _truncate(ev.title, 250),
        "color": COLORS[sum(map(ord, ev.source)) % len(COLORS)],
        "fields": [{"name": "📅 Quand", "value": format_when(ev), "inline": True}],
        "footer": {"text": f"Source : {ev.source}"},
    }
    if ev.url:
        embed["url"] = ev.url
    if ev.description:
        embed["description"] = _truncate(ev.description, 350)
    if ev.location:
        embed["fields"].append(
            {"name": "📍 Où", "value": _truncate(ev.location, 200), "inline": True}
        )
    if ev.image.startswith("http"):
        embed["thumbnail"] = {"url": ev.image}
    return embed


def _embed_size(embed: dict) -> int:
    size = len(embed.get("title", "")) + len(embed.get("description", ""))
    size += len(embed["footer"]["text"])
    size += sum(len(f["name"]) + len(f["value"]) for f in embed["fields"])
    return size


def batches(events: list[Event]):
    """Regroupe les embeds en messages respectant les limites Discord."""
    batch: list[tuple[Event, dict]] = []
    size = 0
    for ev in events:
        embed = build_embed(ev)
        s = _embed_size(embed)
        if batch and (len(batch) >= EMBEDS_PER_MESSAGE or size + s > MAX_CHARS_PER_MESSAGE):
            yield batch
            batch, size = [], 0
        batch.append((ev, embed))
        size += s
    if batch:
        yield batch


def post(webhook_url: str, payload: dict, retries: int = 5) -> None:
    for _ in range(retries):
        resp = requests.post(webhook_url, json=payload, timeout=30)
        if resp.status_code == 429:  # limitation de débit : on attend ce que Discord demande
            wait = float(resp.json().get("retry_after", 2))
            log.info("Discord rate limit, attente %.1fs", wait)
            time.sleep(wait + 0.5)
            continue
        resp.raise_for_status()
        return
    raise RuntimeError("Discord : trop de tentatives (rate limit)")


def send_events(webhook_url: str, events: list[Event], on_sent=None) -> int:
    """Envoie les événements ; `on_sent(event)` est appelé après chaque envoi réussi."""
    sent = 0
    for batch in batches(events):
        post(webhook_url, {
            "username": "Sorties Besançon",
            "embeds": [embed for _, embed in batch],
            "allowed_mentions": {"parse": []},
        })
        for ev, _ in batch:
            sent += 1
            if on_sent:
                on_sent(ev)
        time.sleep(1)  # reste sous la limite de ~30 messages/minute par webhook
    return sent


def send_text(webhook_url: str, content: str) -> None:
    post(webhook_url, {
        "username": "Sorties Besançon",
        "content": content[:2000],
        "allowed_mentions": {"parse": []},
    })
