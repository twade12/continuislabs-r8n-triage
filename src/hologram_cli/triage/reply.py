"""Compose a customer-facing reply from a Diagnosis.

The reply uses the top hypothesis's `customer_summary` as the body, prefixed
with a greeting and signed off with the SE's name. The intent is to produce
something an SE can lightly edit and send — never auto-send.
"""
from __future__ import annotations

from hologram_cli.triage.analyzer import Diagnosis


def draft_reply(diagnosis: Diagnosis, *, sender_name: str = "[Your name]", greeting: str = "Hi there") -> str:
    if not diagnosis.hypotheses:
        body = (
            "Thanks for sending the log. I wasn't able to make a confident call from what's "
            "captured here — could you grab a longer trace that includes AT+CPIN?, AT+CSQ, "
            "AT+CEREG?, AT+CGATT?, AT+CGACT=1,1, and AT+CGPADDR=1? That should give us enough "
            "to pinpoint what's happening."
        )
    else:
        top = diagnosis.hypotheses[0]
        body = top.customer_summary or top.explanation

    return f"{greeting},\n\n{body}\n\nThanks,\n{sender_name}\n"
