"""PostHog analytics wrapper.

All calls are fire-and-forget and never raise — analytics must never
break the app. If POSTHOG_API_KEY is not set, every call is a no-op.
"""
from __future__ import annotations

import os

_key: str = os.environ.get("POSTHOG_API_KEY", "")
_host: str = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")

if _key:
    import posthog as _ph  # type: ignore

    _ph.project_api_key = _key
    _ph.host = _host
    _ph.disabled = False
else:
    _ph = None  # type: ignore


def capture(distinct_id: str, event: str, properties: dict | None = None) -> None:
    if not _ph:
        return
    try:
        _ph.capture(distinct_id, event, properties or {})
    except Exception:
        pass


def identify(distinct_id: str, properties: dict) -> None:
    if not _ph:
        return
    try:
        _ph.identify(distinct_id, properties)
    except Exception:
        pass


def enabled() -> bool:
    return _ph is not None
