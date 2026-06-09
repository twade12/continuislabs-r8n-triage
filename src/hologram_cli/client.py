"""Hologram REST API client.

Thin wrapper over httpx with HTTP Basic auth (apikey:KEY), exponential backoff
on 429 rate limits, and a `mock=True` mode that returns fixture data without
making network calls. Mock mode is useful for development, testing, and demos
without an API key.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from hologram_cli import mock_data
from hologram_cli.config import Profile


class HologramAPIError(RuntimeError):
    pass


@dataclass
class HologramClient:
    profile: Profile
    mock: bool = False
    timeout: float = 15.0

    def get_sim(self, identifier: str) -> dict:
        """Resolve an ICCID, IMEI, device ID, or name to a SIM record."""
        if self.mock:
            sim = mock_data.get_sim(identifier)
            if sim is None:
                raise HologramAPIError(f"SIM not found in mock data: {identifier}")
            return sim
        if identifier.isdigit() and len(identifier) >= 18:
            params = {"orgid": self.profile.org_id, "iccid": identifier}
        elif identifier.isdigit() and len(identifier) == 15:
            params = {"orgid": self.profile.org_id, "imei": identifier}
        else:
            params = {"orgid": self.profile.org_id, "name": identifier}
        body = self._get("/devices/", params=params)
        if not body.get("data"):
            raise HologramAPIError(f"SIM not found: {identifier}")
        return body["data"][0]

    def list_sims(self, *, tag: str | None = None) -> list[dict]:
        if self.mock:
            sims = mock_data.list_sims()
            if tag:
                sims = [s for s in sims if tag in (s.get("tags") or [])]
            return sims
        params: dict[str, Any] = {"orgid": self.profile.org_id}
        if tag:
            params["tagname"] = tag
        body = self._get("/devices/", params=params)
        return body.get("data", [])

    def get_usage(self, deviceid: int, time_start: int, time_end: int) -> dict:
        if self.mock:
            return {"used_mb": 0, "sessions": []}
        return self._get(
            "/usage/data",
            params={"deviceid": deviceid, "timestart": time_start, "timeend": time_end},
        )

    # ---- internals ------------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, params: dict | None = None, json: dict | None = None) -> dict:
        return self._request("POST", path, params=params, json=json)

    def _request(self, method: str, path: str, *, params=None, json=None) -> dict:
        url = f"{self.profile.base_url}{path}"
        auth = ("apikey", self.profile.api_key) if self.profile.api_key else None
        if auth is None:
            raise HologramAPIError("no API key configured; set HOLOGRAM_API_KEY or pass --mock")
        for attempt in range(4):
            with httpx.Client(timeout=self.timeout) as http:
                resp = http.request(method, url, params=params, json=json, auth=auth)
            if resp.status_code == 429:
                time.sleep(min(2 ** attempt, 10))
                continue
            if resp.status_code >= 400:
                raise HologramAPIError(f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                payload = resp.json()
            except ValueError as e:
                raise HologramAPIError(f"non-JSON response from {path}: {e}") from None
            if isinstance(payload, dict) and payload.get("success") is False:
                raise HologramAPIError(payload.get("error") or f"API call failed: {path}")
            return payload
        raise HologramAPIError(f"{method} {path}: rate-limited after retries")
