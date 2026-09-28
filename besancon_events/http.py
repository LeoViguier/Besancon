"""Session HTTP partagée."""

from __future__ import annotations

import requests

USER_AGENT = (
    "Mozilla/5.0 (compatible; BesanconEventsBot/1.0; "
    "+https://github.com/leoviguier/besancon)"
)

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"}
        )
    return _session


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 30)
    resp = session().get(url, **kwargs)
    resp.raise_for_status()
    return resp
