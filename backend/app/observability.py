"""Operational metrics: counts and ages only, never member data.

- feed ages: hours since each stream's last good load, and whether it is stale
- signals per rule: on the latest scoring day
- override rate: audited overrides (not now, snooze, not for me, language) over the last 7 days,
  divided by overrides plus calls started; how often nurses set the suggestion aside
- AI unsupported-sentence rate: unsupported sentences over all drafted sentences
- write-back lag: saves waiting for the CM platform, the oldest one's age, alerts, and the
  median time from save to sync
"""

import statistics
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai_draft.models import AiDraft, AiGuardrailMetric
from app.core.clock import Clock
from app.signals.models import SignalRecord
from app.workbench.feeds import stream_statuses
from app.workbench.models import AuditEvent
from app.writeback.models import WritebackOutbox

OVERRIDES = ("override_not_now", "override_snooze", "override_not_for_me", "override_language")
WINDOW = timedelta(days=7)


def collect(session: Session, clock: Clock) -> dict[str, Any]:
    now = clock.now()
    feeds = [
        {
            "feed": s.feed,
            "stream": s.stream,
            "age_hours": s.age_hours,
            "stale": s.stale,
            "reason": s.reason,
        }
        for s in stream_statuses(session, clock)
    ]

    run_day = session.scalar(select(func.max(SignalRecord.run_day)))
    signals = {
        rule: count
        for rule, count in session.execute(
            select(SignalRecord.rule_id, func.count())
            .where(SignalRecord.run_day == run_day)
            .group_by(SignalRecord.rule_id)
            .order_by(SignalRecord.rule_id)
        )
    }

    since = now - WINDOW
    actions = {
        action: count
        for action, count in session.execute(
            select(AuditEvent.action, func.count())
            .where(
                AuditEvent.at >= since,
                AuditEvent.action.in_((*OVERRIDES, "encounter_started")),
            )
            .group_by(AuditEvent.action)
        )
    }
    overrides = {a: actions.get(a, 0) for a in OVERRIDES}
    overridden = sum(overrides.values())
    decided = overridden + actions.get("encounter_started", 0)

    sentences = unsupported = 0
    for content, count in session.execute(select(AiDraft.content, AiDraft.unsupported_count)):
        sentences += len(content.get("sentences", []))
        unsupported += count
    edits = list(session.scalars(select(AiGuardrailMetric.major_edit)))

    pending = list(
        session.scalars(select(WritebackOutbox).where(WritebackOutbox.status == "pending"))
    )
    synced = list(
        session.execute(
            select(WritebackOutbox.first_attempt_at, WritebackOutbox.synced_at).where(
                WritebackOutbox.synced_at.is_not(None)
            )
        )
    )
    lags = [(s - f).total_seconds() for f, s in synced if f is not None and s is not None]
    alerted = session.scalar(
        select(func.count()).select_from(WritebackOutbox).where(WritebackOutbox.status == "alerted")
    )
    return {
        "at": now.isoformat(),
        "feeds": feeds,
        "signals_per_rule": {"run_day": str(run_day) if run_day else None, "counts": signals},
        "override_rate": {
            "window_days": WINDOW.days,
            "rate": round(overridden / decided, 3) if decided else None,
            "overrides": overrides,
            "calls_started": actions.get("encounter_started", 0),
        },
        "ai": {
            "drafts": session.scalar(select(func.count()).select_from(AiDraft)) or 0,
            "sentences": sentences,
            "unsupported_sentence_rate": round(unsupported / sentences, 3) if sentences else None,
            "major_edit_ratio": round(sum(edits) / len(edits), 3) if edits else None,
        },
        "writeback": {
            "pending": len(pending),
            "oldest_pending_seconds": round(
                max(
                    (now - p.first_attempt_at).total_seconds()
                    for p in pending
                    if p.first_attempt_at
                ),
                1,
            )
            if any(p.first_attempt_at for p in pending)
            else 0,
            "alerted": alerted or 0,
            "synced": len(lags),
            "median_sync_lag_seconds": round(statistics.median(lags), 1) if lags else None,
        },
    }


def _line(name: str, value: float | int | None, **labels: str) -> str | None:
    if value is None:
        return None  # unknown is not zero: the series is left out
    if labels:
        inner = ",".join(f'{k}="{v}"' for k, v in labels.items())
        return f"casecompass_{name}{{{inner}}} {value}"
    return f"casecompass_{name} {value}"


def prometheus(metrics: dict[str, Any]) -> str:
    lines: list[str | None] = [
        "# HELP casecompass_feed_age_hours Hours since the stream's last good load.",
        "# TYPE casecompass_feed_age_hours gauge",
    ]
    for f in metrics["feeds"]:
        lines.append(_line("feed_age_hours", f["age_hours"], feed=f["feed"], stream=f["stream"]))
    lines += ["# TYPE casecompass_feed_stale gauge"]
    for f in metrics["feeds"]:
        lines.append(_line("feed_stale", int(f["stale"]), feed=f["feed"], stream=f["stream"]))
    lines += [
        "# HELP casecompass_signals Signals firing on the latest scoring day, by rule.",
        "# TYPE casecompass_signals gauge",
    ]
    for rule, count in metrics["signals_per_rule"]["counts"].items():
        lines.append(_line("signals", count, rule=rule))
    o = metrics["override_rate"]
    lines += [
        "# HELP casecompass_override_rate Overrides / (overrides + calls started), last 7 days.",
        "# TYPE casecompass_override_rate gauge",
        _line("override_rate", o["rate"]),
        "# TYPE casecompass_overrides gauge",
    ]
    for action, count in o["overrides"].items():
        lines.append(_line("overrides", count, action=action))
    a, w = metrics["ai"], metrics["writeback"]
    lines += [
        "# HELP casecompass_ai_unsupported_sentence_rate Unsupported / drafted sentences.",
        "# TYPE casecompass_ai_unsupported_sentence_rate gauge",
        _line("ai_unsupported_sentence_rate", a["unsupported_sentence_rate"]),
        _line("ai_drafts", a["drafts"]),
        _line("ai_major_edit_ratio", a["major_edit_ratio"]),
        "# HELP casecompass_writeback_pending Saves waiting for the CM platform.",
        "# TYPE casecompass_writeback_pending gauge",
        _line("writeback_pending", w["pending"]),
        _line("writeback_oldest_pending_seconds", w["oldest_pending_seconds"]),
        _line("writeback_alerted", w["alerted"]),
        _line("writeback_median_sync_lag_seconds", w["median_sync_lag_seconds"]),
    ]
    return "\n".join(line for line in lines if line is not None) + "\n"
