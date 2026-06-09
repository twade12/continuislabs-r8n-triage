"""r8n-triage — browser dashboard for IoT connectivity triage.

Architecture:
  - FastAPI shell over the CLI's existing triage modules (no rebuild).
  - Jinja2 + HTMX for server-rendered pages with localized interactivity.
  - SQLite-backed audit log + codex KB (web/db.py).
  - Mock SIM data from hologram_cli.mock_data (the same fixtures the CLI uses).

Route map:
  Public  (no auth): /  /triage  /portal/*  /at  /health  /static
  Admin (Basic Auth): /dash  /sims  /audit  /codex  /bulk  /onboard  /conductor  /fleet  /search
"""
from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from hologram_cli import mock_data
from hologram_cli.triage import analyze, at_reference, draft_reply, parse
from hologram_cli.triage.oracle import explain_state
from web import analytics, db, seed
from web.auth import get_current_user, get_distinct_id
from web.auth import router as auth_router

BASE_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = BASE_DIR.parent / "fixtures" / "at_logs"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

MAX_LOG_BYTES = 200_000  # 200 KB hard limit on triage input

app = FastAPI(title="r8n-triage", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Session middleware must be added before any route that reads request.session
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me-in-production"),
    https_only=os.environ.get("APP_URL", "").startswith("https"),
)
app.include_router(auth_router)

# Make PostHog key available to every template without passing it explicitly
templates.env.globals["posthog_key"] = os.environ.get("POSTHOG_API_KEY", "")
templates.env.globals["posthog_host"] = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")

# ---- Auth ------------------------------------------------------------------

_security = HTTPBasic(auto_error=False)


def _admin_auth(credentials: HTTPBasicCredentials | None = Depends(_security)) -> str:
    """Require HTTP Basic Auth for admin routes. Credentials from env vars."""
    expected_user = os.environ.get("ADMIN_USER", "admin").encode()
    expected_pass = os.environ.get("ADMIN_PASS", "changeme").encode()
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    user_ok = secrets.compare_digest(credentials.username.encode(), expected_user)
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected_pass)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# ---- Sample log registry ---------------------------------------------------

def _load_samples() -> dict[str, dict]:
    """Parse fixture AT logs into a name → {title, content} registry."""
    samples: dict[str, dict] = {}
    if not FIXTURES_DIR.exists():
        return samples
    for path in sorted(FIXTURES_DIR.glob("*.log")):
        title_line = ""
        for line in path.read_text(errors="replace").splitlines():
            stripped = line.lstrip("# ").strip()
            if stripped.lower().startswith("scenario:"):
                title_line = stripped[len("scenario:"):].strip()
                break
        slug = re.sub(r"^\d+_", "", path.stem)  # strip leading "01_"
        samples[slug] = {"title": title_line or slug.replace("_", " "), "path": path}
    return samples


_SAMPLES: dict[str, dict] = {}


# ---- Startup ---------------------------------------------------------------


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    seed.seed_if_empty()
    global _SAMPLES
    _SAMPLES = _load_samples()


def ctx(request: Request, **kwargs) -> dict:
    """Base template context — injects current_user into every response."""
    return {"request": request, "current_user": get_current_user(request), **kwargs}


# ---- Health check (public) -------------------------------------------------


@app.get("/health")
def health() -> JSONResponse:
    try:
        db.list_triage(limit=1)
        db_ok = True
    except Exception:
        db_ok = False
    return JSONResponse({"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "error", "version": "0.1.0"})


# ---- Public landing page ---------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "landing.html", ctx(request))


# ---- Phase 1: triage workbench (PUBLIC) ------------------------------------


@app.get("/triage", response_class=HTMLResponse)
def triage_page(
    request: Request,
    log: Optional[str] = None,
    iccid: Optional[str] = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "triage.html",
        ctx(
            request,
            active_page="triage",
            preset_log=log or "",
            preset_iccid=iccid or "",
            samples={k: v["title"] for k, v in _SAMPLES.items()},
        ),
    )


@app.get("/triage/sample/{name}", response_class=HTMLResponse)
def triage_sample(name: str) -> HTMLResponse:
    """Return raw fixture log text for inline loading via fetch."""
    sample = _SAMPLES.get(name)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    content = sample["path"].read_text(errors="replace")
    return HTMLResponse(content=content, media_type="text/plain")


@app.post("/triage/diagnose", response_class=HTMLResponse)
def triage_diagnose(
    request: Request,
    raw_log: str = Form(...),
    customer_msg: str = Form(""),
    iccid: str = Form(""),
    sender: str = Form("[Your name]"),
    persist: str = Form(""),
) -> HTMLResponse:
    if len(raw_log.encode()) > MAX_LOG_BYTES:
        return HTMLResponse(
            "<div class='bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700'>"
            "Log exceeds the 200 KB size limit. Please trim and resubmit.</div>"
        )
    log = parse(raw_log)
    diagnosis = analyze(log)
    reply = draft_reply(diagnosis, sender_name=sender or "[Your name]")
    top = diagnosis.hypotheses[0] if diagnosis.hypotheses else None
    similar = db.find_similar_codex(
        vendor=log.vendor, module=log.module, rule_id=top.rule_id if top else None,
    )
    sim_info = mock_data.get_sim(iccid) if iccid else None
    sim_explanation = explain_state(sim_info) if sim_info else None

    user = get_current_user(request)
    session_id: Optional[str] = None
    if persist == "on":
        session_id = db.save_triage(
            raw_log=raw_log,
            customer_msg=customer_msg or None,
            iccid=iccid or None,
            vendor=log.vendor,
            module=log.module,
            diagnosis=diagnosis.as_dict(),
            reply_drafted=reply,
            user_id=user["id"] if user else None,
        )

    analytics.capture(
        get_distinct_id(request),
        "triage_submitted",
        {
            "vendor": log.vendor,
            "module": log.module,
            "top_rule": top.rule_id if top else None,
            "confidence": top.confidence if top else None,
            "has_iccid": bool(iccid),
            "persisted": persist == "on",
            "logged_in": bool(user),
        },
    )

    return templates.TemplateResponse(
        request,
        "partials/triage_result.html",
        ctx(
            request,
            diagnosis=diagnosis,
            reply=reply,
            vendor=log.vendor,
            module=log.module,
            similar=similar,
            sim_info=sim_info,
            sim_explanation=sim_explanation,
            session_id=session_id,
        ),
    )


# ---- Admin dashboard (/dash — requires auth) --------------------------------


@app.get("/dash", response_class=HTMLResponse)
def home(request: Request, _: str = Depends(_admin_auth)) -> HTMLResponse:
    rule_counts = db.aggregate_by_rule(days=30)
    recent = db.list_triage(limit=8)
    sims = mock_data.list_sims()
    by_state = Counter(s["state"] for s in sims)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
            "rule_counts": rule_counts,
            "recent_sessions": recent,
            "sim_count": len(sims),
            "state_distribution": dict(by_state),
            "active_page": "dash",
        },
    )


# ---- SIM detail (public read — uses mock data) ----------------------------


@app.get("/sims/{iccid}", response_class=HTMLResponse)
def sim_detail(request: Request, iccid: str, _: str = Depends(_admin_auth)) -> HTMLResponse:
    sim = mock_data.get_sim(iccid)
    if sim is None:
        return HTMLResponse(f"<h2>SIM not found: {iccid}</h2>", status_code=404)
    explanation = explain_state(sim)
    history = sorted(sim.get("state_history") or [], key=lambda e: e["ts"])
    return templates.TemplateResponse(
        request,
        "sim_detail.html",
        {
            "request": request,
            "active_page": "sims",
            "sim": sim,
            "explanation": explanation,
            "state_history": history,
        },
    )


# ---- Phase 2: SIMs index, audit log, codex KB, AT reference, search -------


@app.get("/sims", response_class=HTMLResponse)
def sims_index(
    request: Request,
    state: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    _: str = Depends(_admin_auth),
) -> HTMLResponse:
    sims = mock_data.list_sims()
    if state:
        sims = [s for s in sims if s.get("state") == state]
    if tag:
        sims = [s for s in sims if tag in (s.get("tags") or [])]
    if q:
        ql = q.lower()
        sims = [
            s for s in sims
            if ql in (s.get("iccid") or "").lower()
            or ql in (s.get("name") or "").lower()
            or ql in (s.get("imei") or "").lower()
        ]
    states = sorted({s.get("state") for s in mock_data.list_sims()})
    tags = sorted({t for s in mock_data.list_sims() for t in (s.get("tags") or [])})
    return templates.TemplateResponse(
        request,
        "sims_index.html",
        {
            "request": request,
            "active_page": "sims",
            "sims": sims,
            "states": states,
            "tags": tags,
            "filter_state": state,
            "filter_tag": tag,
            "query": q or "",
        },
    )


@app.get("/audit", response_class=HTMLResponse)
def audit_log(
    request: Request,
    rule_id: Optional[str] = None,
    _: str = Depends(_admin_auth),
) -> HTMLResponse:
    sessions = db.list_triage(limit=200, rule_id=rule_id)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "request": request,
            "active_page": "audit",
            "sessions": sessions,
            "filter_rule": rule_id,
        },
    )


@app.get("/audit/{sid}", response_class=HTMLResponse)
def audit_detail(request: Request, sid: str, _: str = Depends(_admin_auth)) -> HTMLResponse:
    session = db.get_triage(sid)
    if not session:
        return HTMLResponse("<h2>Session not found</h2>", status_code=404)
    return templates.TemplateResponse(
        request,
        "audit_detail.html",
        {"request": request, "active_page": "audit", "s": session},
    )


@app.post("/audit/{sid}/outcome")
def audit_save_outcome(
    sid: str,
    outcome: str = Form(...),
    cause: str = Form(""),
    ticket_ref: str = Form(""),
    _: str = Depends(_admin_auth),
) -> RedirectResponse:
    db.update_triage_outcome(sid, outcome, cause or None, ticket_ref or None)
    return RedirectResponse(f"/audit/{sid}", status_code=303)


@app.get("/codex", response_class=HTMLResponse)
def codex_index(
    request: Request,
    vendor: Optional[str] = None,
    module: Optional[str] = None,
    symptom: Optional[str] = None,
    q: Optional[str] = None,
    _: str = Depends(_admin_auth),
) -> HTMLResponse:
    entries = db.list_codex(vendor=vendor, module=module, symptom=symptom, q=q)
    all_entries = db.list_codex()
    vendors = sorted({e["vendor"] for e in all_entries if e.get("vendor")})
    modules = sorted({e["module"] for e in all_entries if e.get("module")})
    symptoms = sorted({t for e in all_entries for t in (e.get("symptom_tags") or [])})
    return templates.TemplateResponse(
        request,
        "codex.html",
        {
            "request": request,
            "active_page": "codex",
            "entries": entries,
            "vendors": vendors,
            "modules": modules,
            "symptoms": symptoms,
            "filter_vendor": vendor or "",
            "filter_module": module or "",
            "filter_symptom": symptom or "",
            "query": q or "",
        },
    )


@app.get("/codex/new", response_class=HTMLResponse)
def codex_new_form(
    request: Request,
    from_session: Optional[str] = None,
    _: str = Depends(_admin_auth),
) -> HTMLResponse:
    prefill = {}
    if from_session:
        s = db.get_triage(from_session)
        if s:
            top = (s.get("diagnosis", {}).get("hypotheses") or [{}])[0]
            prefill = {
                "vendor": s.get("vendor") or "",
                "module": s.get("module") or "",
                "title": top.get("title", "")[:120],
                "symptom_tags": top.get("rule_id", ""),
                "diagnosis": top.get("explanation", ""),
                "source_session_id": from_session,
            }
    return templates.TemplateResponse(
        request,
        "codex_new.html",
        {"request": request, "active_page": "codex", "prefill": prefill},
    )


@app.post("/codex")
def codex_create(
    title: str = Form(...),
    vendor: str = Form(""),
    module: str = Form(""),
    carrier: str = Form(""),
    rat: str = Form(""),
    symptom_tags: str = Form(""),
    diagnosis: str = Form(""),
    fix: str = Form(""),
    source_session_id: str = Form(""),
    _: str = Depends(_admin_auth),
) -> RedirectResponse:
    tags = [t.strip() for t in symptom_tags.split(",") if t.strip()]
    cid = db.save_codex(
        title=title,
        vendor=vendor or None,
        module=module or None,
        carrier=carrier or None,
        rat=rat or None,
        symptom_tags=tags,
        diagnosis=diagnosis,
        fix=fix,
        source_session_id=source_session_id or None,
    )
    return RedirectResponse(f"/codex/{cid}", status_code=303)


@app.get("/codex/{cid}", response_class=HTMLResponse)
def codex_detail(request: Request, cid: str, _: str = Depends(_admin_auth)) -> HTMLResponse:
    entry = db.get_codex(cid)
    if not entry:
        return HTMLResponse("<h2>Entry not found</h2>", status_code=404)
    return templates.TemplateResponse(
        request,
        "codex_entry.html",
        {"request": request, "active_page": "codex", "e": entry},
    )


@app.post("/codex/{cid}/upvote")
def codex_upvote(cid: str, _: str = Depends(_admin_auth)) -> RedirectResponse:
    db.upvote_codex(cid)
    return RedirectResponse(f"/codex/{cid}", status_code=303)


@app.get("/at", response_class=HTMLResponse)
def at_index(request: Request, vendor: Optional[str] = None) -> HTMLResponse:
    """AT reference is public — it's a useful standalone resource."""
    commands = at_reference.list_commands(vendor=vendor)
    by_vendor: dict[str, list] = {}
    for c in commands:
        by_vendor.setdefault(c.vendor, []).append(c)
    return templates.TemplateResponse(
        request,
        "at_reference.html",
        {
            "request": request,
            "active_page": "at",
            "by_vendor": by_vendor,
            "filter_vendor": vendor or "",
        },
    )


@app.post("/at/decode", response_class=HTMLResponse)
def at_decode(request: Request, line: str = Form(...)) -> HTMLResponse:
    result = at_reference.decode_response(line.strip())
    analytics.capture(get_distinct_id(request), "at_response_decoded")
    return templates.TemplateResponse(
        request,
        "partials/at_decode_result.html",
        {"request": request, "line": line, "result": result},
    )


@app.get("/at/lookup", response_class=HTMLResponse)
def at_lookup(request: Request, name: str) -> HTMLResponse:
    cmd = at_reference.lookup(name)
    analytics.capture(get_distinct_id(request), "at_command_looked_up", {"command": name})
    return templates.TemplateResponse(
        request,
        "partials/at_lookup_result.html",
        {"request": request, "cmd": cmd, "name": name},
    )


@app.get("/search", response_class=HTMLResponse)
def global_search(request: Request, q: str = "", _: str = Depends(_admin_auth)) -> HTMLResponse:
    sim_hits = []
    if q:
        sim = mock_data.get_sim(q)
        if sim:
            sim_hits.append(sim)
        for s in mock_data.list_sims():
            if s in sim_hits:
                continue
            ql = q.lower()
            if (ql in (s.get("iccid") or "").lower() or
                ql in (s.get("name") or "").lower() or
                ql in (s.get("imei") or "").lower()):
                sim_hits.append(s)
    codex_hits = db.list_codex(q=q, limit=10) if q else []
    cmd_hits = at_reference.search(q) if q else []
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "request": request,
            "active_page": None,
            "query": q,
            "sim_hits": sim_hits,
            "codex_hits": codex_hits,
            "cmd_hits": cmd_hits,
        },
    )


# ---- Phase 3: fleet health -------------------------------------------------


@app.get("/fleet", response_class=HTMLResponse)
def fleet_health(request: Request, _: str = Depends(_admin_auth)) -> HTMLResponse:
    rule_counts = db.aggregate_by_rule(days=30)
    by_module = db.aggregate_by_module()
    sims = mock_data.list_sims()
    state_dist = Counter(s["state"] for s in sims)
    tag_dist = Counter(t for s in sims for t in (s.get("tags") or []))

    fault_states = {"PAUSED-SYS", "LIVE-PENDING"}
    flagged = [s for s in sims if s.get("state") in fault_states]
    hot_groups: dict[str, list] = {}
    for s in flagged:
        for t in (s.get("tags") or []):
            hot_groups.setdefault(t, []).append(s)
    hot_groups_sorted = sorted(
        ((tag, items) for tag, items in hot_groups.items() if len(items) >= 1),
        key=lambda x: -len(x[1]),
    )

    return templates.TemplateResponse(
        request,
        "fleet.html",
        {
            "request": request,
            "active_page": "fleet",
            "rule_counts": rule_counts,
            "by_module": by_module,
            "state_dist": dict(state_dist),
            "tag_dist": dict(tag_dist),
            "hot_groups": hot_groups_sorted[:6],
        },
    )


# ---- Phase 4: bulk ops, onboarding wizard, conductor ----------------------


@app.get("/bulk", response_class=HTMLResponse)
def bulk_index(request: Request, _: str = Depends(_admin_auth)) -> HTMLResponse:
    sims = mock_data.list_sims()
    recent = db.list_bulk_ops()
    return templates.TemplateResponse(
        request,
        "bulk.html",
        {
            "request": request,
            "active_page": "bulk",
            "sims": sims,
            "recent_ops": recent,
        },
    )


@app.post("/bulk/execute")
def bulk_execute(
    op_type: str = Form(...),
    iccids: list[str] = Form(...),
    note: str = Form(""),
    _: str = Depends(_admin_auth),
) -> RedirectResponse:
    db.save_bulk_op(
        op_type=op_type,
        target_count=len(iccids),
        details={"iccids": iccids, "note": note, "executed": False, "dry_run": True},
    )
    return RedirectResponse("/bulk", status_code=303)


@app.get("/onboard", response_class=HTMLResponse)
def onboard_wizard(
    request: Request,
    step: int = 1,
    _: str = Depends(_admin_auth),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "onboard.html",
        {
            "request": request,
            "active_page": "onboard",
            "step": step,
        },
    )


@app.post("/onboard")
def onboard_submit(
    step: int = Form(...),
    next_step: int = Form(...),
    _: str = Depends(_admin_auth),
) -> RedirectResponse:
    return RedirectResponse(f"/onboard?step={next_step}", status_code=303)


@app.get("/conductor", response_class=HTMLResponse)
def conductor_console(request: Request, _: str = Depends(_admin_auth)) -> HTMLResponse:
    sims = mock_data.list_sims()
    hyper = [s for s in sims if "hyper-sim" in (s.get("tags") or []) or s.get("euicc_profiles")]
    profile_dist: Counter = Counter()
    for s in sims:
        profiles = s.get("euicc_profiles") or []
        for p in profiles:
            if p.get("active"):
                profile_dist[p.get("carrier", "unknown")] += 1
    policies = db.list_policies()
    switches = db.list_switches(limit=20)
    return templates.TemplateResponse(
        request,
        "conductor.html",
        {
            "request": request,
            "active_page": "conductor",
            "hyper_sims": hyper,
            "profile_dist": dict(profile_dist),
            "policies": policies,
            "switches": switches,
        },
    )


@app.post("/conductor/policy")
def conductor_create_policy(
    name: str = Form(...),
    scope: str = Form(...),
    rule: str = Form(...),
    _: str = Depends(_admin_auth),
) -> RedirectResponse:
    db.save_policy(name, scope, rule)
    return RedirectResponse("/conductor", status_code=303)


@app.post("/conductor/policy/{pid}/toggle")
def conductor_toggle_policy(pid: str, _: str = Depends(_admin_auth)) -> RedirectResponse:
    db.toggle_policy(pid)
    return RedirectResponse("/conductor", status_code=303)


@app.post("/conductor/switch/{iccid}")
def conductor_switch(
    iccid: str,
    new_profile: str = Form(...),
    _: str = Depends(_admin_auth),
) -> RedirectResponse:
    sim = mock_data.get_sim(iccid)
    old = "unknown"
    if sim:
        for p in sim.get("euicc_profiles") or []:
            if p.get("active"):
                old = p.get("carrier", "unknown")
    db.save_switch(iccid, old, new_profile, "manual:dashboard")
    return RedirectResponse("/conductor", status_code=303)


# ---- Phase 5: customer self-service portal (public) -----------------------


@app.get("/portal", response_class=HTMLResponse)
def portal_home(request: Request) -> HTMLResponse:
    customer_tag = "fleet:trucks"
    sims = [s for s in mock_data.list_sims() if customer_tag in (s.get("tags") or [])]
    return templates.TemplateResponse(
        request,
        "portal_home.html",
        {
            "request": request,
            "active_page": "portal",
            "sims": sims,
            "customer_name": "FleetCo (demo)",
        },
    )


@app.get("/portal/triage", response_class=HTMLResponse)
def portal_triage(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "portal_triage.html",
        {"request": request, "active_page": "portal"},
    )


@app.post("/portal/triage/diagnose", response_class=HTMLResponse)
def portal_triage_diagnose(
    request: Request,
    raw_log: str = Form(...),
) -> HTMLResponse:
    if len(raw_log.encode()) > MAX_LOG_BYTES:
        return HTMLResponse(
            "<div class='bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700'>"
            "Log exceeds the 200 KB size limit. Please trim and resubmit.</div>"
        )
    log = parse(raw_log)
    diagnosis = analyze(log)
    return templates.TemplateResponse(
        request,
        "partials/portal_triage_result.html",
        {
            "request": request,
            "diagnosis": diagnosis,
            "vendor": log.vendor,
            "module": log.module,
        },
    )
