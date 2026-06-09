"""State oracle: explain WHY a SIM is in its current state.

Given a SIM record (from the API or mock data), match the state and recent
history against known patterns and produce a plain-language explanation
plus suggested next actions. This is the deterministic counterpart to the
AT-log analyzer — same shape, different input.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StateExplanation:
    state: str
    summary: str
    explanation: str
    next_actions: list[str] = field(default_factory=list)
    severity: str = "info"  # info | warning | critical

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "summary": self.summary,
            "explanation": self.explanation,
            "next_actions": self.next_actions,
            "severity": self.severity,
        }


def explain_state(sim: dict) -> StateExplanation:
    state = sim.get("state", "UNKNOWN")
    handler = _HANDLERS.get(state, _explain_unknown)
    return handler(sim)


def _explain_live(sim: dict) -> StateExplanation:
    last = sim.get("last_session")
    if last and (time.time() - last["ts"]) > 86400 * 7:
        return StateExplanation(
            state="LIVE",
            summary="SIM is active but hasn't connected in over 7 days",
            explanation=(
                "The SIM's billing/account state is healthy — it's authorized to use the network. "
                "But there's been no session in over a week, which usually points to a device-side "
                "problem: power, antenna, firmware crash, or the device being stored offline."
            ),
            next_actions=[
                "Confirm the device is powered on and has antenna coverage at its current location.",
                "Pull modem-side logs (AT+CEREG?, AT+CSQ, AT+QENG=\"servingcell\") if you can reach the device.",
                "If the device is intentionally offline (warehouse / decommissioned), consider pausing the SIM to avoid plan minimums.",
            ],
            severity="warning",
        )
    return StateExplanation(
        state="LIVE",
        summary="SIM is active and online",
        explanation="The SIM is in the LIVE state with recent sessions. No action needed.",
        next_actions=[],
        severity="info",
    )


def _explain_live_pending(sim: dict) -> StateExplanation:
    age = _state_age(sim)
    if age is not None and age < 600:
        return StateExplanation(
            state="LIVE-PENDING",
            summary="Activation is in progress (under 10 minutes old)",
            explanation=(
                "The SIM is being configured at the carrier. Initial activation can take up to "
                "15 minutes to propagate. If the device tries to attach before propagation "
                "completes, you'll typically see +CEREG: 0,3 (registration denied) on the modem."
            ),
            next_actions=[
                "Wait at least 15 minutes from activation, then power-cycle the device.",
                "If still not connecting after 60 minutes, escalate with the ICCID and activation timestamp.",
            ],
            severity="info",
        )
    return StateExplanation(
        state="LIVE-PENDING",
        summary="Activation has been pending for an unusually long time",
        explanation=(
            "The SIM has been in LIVE-PENDING for longer than typical (>10 minutes). This may "
            "indicate a stuck propagation at the carrier or a backend issue."
        ),
        next_actions=[
            "Try resuming activation from the dashboard (or POST to /links/cellular/{linkid}/state with state=live).",
            "If still stuck after another 30 minutes, escalate to L3 with the ICCID and the original activation timestamp.",
        ],
        severity="warning",
    )


def _explain_paused_user(sim: dict) -> StateExplanation:
    return StateExplanation(
        state="PAUSED-USER",
        summary="Manually paused by an organization member",
        explanation=(
            "Someone in your org clicked Pause on the dashboard or called the pause API. "
            "Data and SMS are blocked until the SIM is resumed."
        ),
        next_actions=[
            "Confirm whether the pause was intentional — check team activity or audit log.",
            "If the pause was a mistake, resume via the dashboard or POST /links/cellular/{linkid}/state with state=live.",
            "After resume, allow up to 10 minutes for the change to take effect at the carrier.",
        ],
        severity="info",
    )


def _explain_paused_sys(sim: dict) -> StateExplanation:
    used = (sim.get("current_period") or {}).get("used_mb")
    plan = sim.get("plan") or {}
    limit = plan.get("limit_mb")
    over_limit = used is not None and limit is not None and used >= limit
    hint = sim.get("pause_reason_hint")

    if hint == "data_cap_exceeded" or over_limit:
        return StateExplanation(
            state="PAUSED-SYS",
            summary=f"System-paused — data cap exceeded ({used} MB on a {limit} MB plan)",
            explanation=(
                "PAUSED-SYS means the system suspended this SIM. The most common reason is that "
                "current-period usage exceeded the configured plan limit. Other possible causes "
                "include account balance issues or org-level overage policies firing."
            ),
            next_actions=[
                "Confirm the data cap was the trigger (verify in the dashboard's billing tab).",
                "Decide on response: bump the plan, raise the per-SIM cap, or accept the pause until next cycle.",
                "If it's recurring, consider tagging this device for a higher-tier plan to prevent monthly disruption.",
                "After resolution, expect up to 10 minutes for the resume to settle.",
            ],
            severity="critical",
        )
    return StateExplanation(
        state="PAUSED-SYS",
        summary="System-paused — reason unclear from available data",
        explanation=(
            "The SIM was paused by the system but available indicators don't pinpoint the cause. "
            "Common reasons: plan/data cap, balance, or org-level policy."
        ),
        next_actions=[
            "Check the SIM's billing tab in the dashboard for cap/balance flags.",
            "Inspect any recent state changes for context.",
            "If unclear, escalate to support with the ICCID.",
        ],
        severity="warning",
    )


def _explain_test_activate(sim: dict) -> StateExplanation:
    used_mb = (sim.get("current_period") or {}).get("used_mb", 0)
    used_kb = used_mb * 1024
    return StateExplanation(
        state="TEST-ACTIVATE",
        summary=f"In testing window — {used_kb:.0f} KB used of 100 KB allowance",
        explanation=(
            "TEST-ACTIVATE allows up to 100 KB of data or 10 SMS for free, then auto-converts to "
            "LIVE on a paid plan. If the customer expects ongoing data, they need to manually "
            "promote to LIVE before exhausting the allowance, or wait for the auto-conversion."
        ),
        next_actions=[
            "If this SIM is going into production, click Activate in the dashboard and assign a plan.",
            "If it's an internal test SIM, no action needed — auto-conversion will happen at quota.",
            "Watch for the silent failure mode: if data fails after attach succeeds, suspect quota exhaustion.",
        ],
        severity="info",
    )


def _explain_dead(sim: dict) -> StateExplanation:
    return StateExplanation(
        state="DEAD",
        summary="Permanently deactivated — cannot be reactivated",
        explanation=(
            "DEAD is a terminal state. The SIM has been permanently deactivated and cannot be "
            "brought back to LIVE. Provision a replacement SIM if the device needs to come back online."
        ),
        next_actions=[
            "If the deactivation was a mistake, escalate IMMEDIATELY — terminal state means action is irreversible.",
            "Otherwise, claim and activate a replacement SIM and update the device.",
        ],
        severity="warning",
    )


def _explain_unknown(sim: dict) -> StateExplanation:
    state = sim.get("state", "UNKNOWN")
    return StateExplanation(
        state=state,
        summary=f"Unrecognized state: {state}",
        explanation=(
            f"The state '{state}' is not handled by the oracle. This may be a transitional state "
            "(check back in 5–10 minutes) or a new state Hologram has added that isn't yet modeled here."
        ),
        next_actions=[
            "Re-fetch the SIM in 5–10 minutes — transitional states (PENDING variants) usually resolve quickly.",
            "If the state persists, consult https://docs.hologram.io/dashboard/sims/sim-states-and-statuses",
        ],
        severity="warning",
    )


_HANDLERS = {
    "LIVE": _explain_live,
    "LIVE-PENDING": _explain_live_pending,
    "PAUSED-USER": _explain_paused_user,
    "PAUSED-SYS": _explain_paused_sys,
    "PAUSE-PENDING-USER": _explain_paused_user,
    "PAUSE-PENDING-SYS": _explain_paused_sys,
    "TEST-ACTIVATE": _explain_test_activate,
    "TEST-ACTIVATE-PENDING": _explain_test_activate,
    "DEAD": _explain_dead,
    "DEAD-PENDING": _explain_dead,
    "INACTIVE": lambda sim: StateExplanation(
        state="INACTIVE",
        summary="SIM is claimed but not yet activated",
        explanation="An INACTIVE SIM is sitting in inventory, ready to activate. No data services available.",
        next_actions=["Activate via the dashboard or POST /links/cellular/bulkclaim when ready to deploy."],
        severity="info",
    ),
}


def _state_age(sim: dict) -> int | None:
    history = sim.get("state_history") or []
    if not history:
        return None
    last_change = max(entry["ts"] for entry in history if entry["state"] == sim.get("state"))
    return int(time.time() - last_change)
