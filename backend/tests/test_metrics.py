"""Observability: /metrics (Prometheus text) and /admin/metrics (JSON for supervisors)."""

import re

from tests.api.conftest import Api, api, api_template  # noqa: F401  (API fixtures)
from tests.writeback.test_writeback import ready_to_save


def test_prometheus_metrics_cover_feeds_signals_overrides_ai_and_writeback(api: Api) -> None:
    text = api.client.get("/metrics").text

    assert re.search(r'casecompass_feed_age_hours\{feed="pharmacy",stream="pharmacy_ncpdp"\} \d', text)
    assert 'casecompass_feed_stale{feed="claims",stream="claims_837"} 1' in text
    assert re.search(r'casecompass_signals\{rule="NO_CRITICAL_MED_ON_HAND"\} [1-9]', text)
    assert 'casecompass_overrides{action="override_not_now"} 0' in text
    assert "casecompass_writeback_pending 0" in text
    # No calls and no drafts yet: those rates are unknown, so they are left out, not 0.
    assert "casecompass_override_rate " not in text
    assert "casecompass_ai_unsupported_sentence_rate " not in text


def test_metrics_never_contain_member_data(api: Api) -> None:
    text = api.client.get("/metrics").text
    assert not re.search(r"SYN-\d|555-01|Raymond|Tull", text)


def test_override_rate_and_writeback_lag_move_with_the_work(api: Api) -> None:
    maria = api.as_("maria")
    api.client.post(
        "/members/SYN-005/not-now",
        json={"reason": "family meeting this afternoon", "rule_id": "LTSS_HOURS_CUT"},
        headers=maria,
    )
    eid = ready_to_save(api)  # starts Raymond's call
    api.cm.post("/admin/mode", json={"mode": "down"})
    api.client.post(f"/encounters/{eid}/save", headers=maria)

    body = api.client.get("/admin/metrics", headers=api.as_("janet")).json()

    assert body["override_rate"]["overrides"]["override_not_now"] == 1
    assert body["override_rate"]["calls_started"] == 1
    assert body["override_rate"]["rate"] == 0.5
    assert body["writeback"]["pending"] == 1
    assert body["signals_per_rule"]["counts"]["NO_CRITICAL_MED_ON_HAND"] >= 1
    assert api.client.get("/admin/metrics", headers=maria).status_code == 403  # supervisors only
