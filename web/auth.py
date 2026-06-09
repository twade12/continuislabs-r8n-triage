"""Google + GitHub OAuth routes and session helpers."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from web import analytics, db

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/auth", tags=["auth"])

# APP_URL is used to build OAuth callback URLs in production (behind Caddy/nginx).
# In dev it falls back to request.url_for() which uses localhost.
# Example: APP_URL=https://r8n.continuislabs.cloud
_APP_URL = os.environ.get("APP_URL", "").rstrip("/")

oauth = OAuth()

_google_id = os.environ.get("GOOGLE_CLIENT_ID", "")
_google_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
_github_id = os.environ.get("GITHUB_CLIENT_ID", "")
_github_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")

if _google_id:
    oauth.register(
        name="google",
        client_id=_google_id,
        client_secret=_google_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

if _github_id:
    oauth.register(
        name="github",
        client_id=_github_id,
        client_secret=_github_secret,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "read:user user:email"},
    )


# ---- Session helpers -------------------------------------------------------


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def get_distinct_id(request: Request) -> str:
    """Stable analytics ID — user.id if logged in, else a session-scoped UUID."""
    user = request.session.get("user")
    if user:
        return user["id"]
    anon_id = request.session.get("anon_id")
    if not anon_id:
        anon_id = str(uuid.uuid4())
        request.session["anon_id"] = anon_id
    return anon_id


def _callback_url(request: Request, route_name: str) -> str:
    """Return the OAuth callback URL, using APP_URL in production."""
    if _APP_URL:
        # Strip the host from url_for and prepend the configured base URL
        path = str(request.url_for(route_name)).split("/", 3)[-1]
        return f"{_APP_URL}/{path}"
    return str(request.url_for(route_name))


def _store_session(request: Request, user: dict) -> None:
    request.session["user"] = {
        "id": user["id"],
        "email": user.get("email") or "",
        "name": user.get("name") or "",
        "avatar_url": user.get("avatar_url") or "",
        "provider": user.get("provider") or "",
    }


# ---- Routes ----------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/triage") -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "request": request,
            "next": next,
            "current_user": get_current_user(request),
            "has_google": bool(_google_id),
            "has_github": bool(_github_id),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/google")
async def auth_google(request: Request, next: str = "/triage") -> RedirectResponse:
    if not _google_id:
        return RedirectResponse("/auth/login?error=google_not_configured", 303)
    request.session["oauth_next"] = next
    redirect_uri = _callback_url(request, "auth_google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="auth_google_callback")
async def auth_google_callback(request: Request) -> RedirectResponse:
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse("/auth/login?error=google_failed", 303)

    info = token.get("userinfo") or {}
    user = db.get_or_create_user(
        provider="google",
        provider_id=str(info.get("sub", "")),
        email=info.get("email"),
        name=info.get("name"),
        avatar_url=info.get("picture"),
    )
    _store_session(request, user)
    analytics.capture(user["id"], "user_logged_in", {"provider": "google"})
    if user.get("_new"):
        analytics.capture(user["id"], "user_signed_up", {"provider": "google"})
        analytics.identify(user["id"], {"email": user.get("email"), "name": user.get("name")})

    return RedirectResponse(request.session.pop("oauth_next", "/triage"), 303)


@router.get("/github")
async def auth_github(request: Request, next: str = "/triage") -> RedirectResponse:
    if not _github_id:
        return RedirectResponse("/auth/login?error=github_not_configured", 303)
    request.session["oauth_next"] = next
    redirect_uri = _callback_url(request, "auth_github_callback")
    return await oauth.github.authorize_redirect(request, redirect_uri)


@router.get("/github/callback", name="auth_github_callback")
async def auth_github_callback(request: Request) -> RedirectResponse:
    try:
        token = await oauth.github.authorize_access_token(request)
    except Exception:
        return RedirectResponse("/auth/login?error=github_failed", 303)

    resp = await oauth.github.get("user", token=token)
    resp.raise_for_status()
    gh = resp.json()

    email: str | None = gh.get("email")
    if not email:
        emails_resp = await oauth.github.get("user/emails", token=token)
        if emails_resp.status_code == 200:
            for e in emails_resp.json():
                if e.get("primary") and e.get("verified"):
                    email = e["email"]
                    break

    user = db.get_or_create_user(
        provider="github",
        provider_id=str(gh.get("id", "")),
        email=email,
        name=gh.get("name") or gh.get("login"),
        avatar_url=gh.get("avatar_url"),
    )
    _store_session(request, user)
    analytics.capture(user["id"], "user_logged_in", {"provider": "github"})
    if user.get("_new"):
        analytics.capture(user["id"], "user_signed_up", {"provider": "github"})
        analytics.identify(user["id"], {"email": user.get("email"), "name": user.get("name")})

    return RedirectResponse(request.session.pop("oauth_next", "/triage"), 303)


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.pop("user", None)
    return RedirectResponse("/", 303)
