"""阶段十三资源配额公开行为测试。"""

from decimal import Decimal

import pytest

from app.monitoring.quotas import QuotaConfigurationError, QuotaPolicy


def test_quota_policy_warns_at_the_inclusive_warning_boundary() -> None:
    decision = QuotaPolicy().evaluate(
        used_bytes=700,
        capacity_bytes=1_000,
        requested_bytes=0,
    )

    assert decision.state == "warning"
    assert decision.projected_bytes == 700


def test_quota_policy_rejects_zero_capacity_as_invalid_configuration() -> None:
    with pytest.raises(QuotaConfigurationError, match="容量必须大于零"):
        QuotaPolicy().evaluate(
            used_bytes=0,
            capacity_bytes=0,
            requested_bytes=1,
        )


def test_quota_policy_rejects_thresholds_that_cannot_form_a_warning_band() -> None:
    with pytest.raises(QuotaConfigurationError, match="阈值"):
        QuotaPolicy(
            warning_ratio=Decimal("0.85"),
            hard_limit_ratio=Decimal("0.85"),
        )


def test_quota_policy_rejects_negative_usage_instead_of_treating_it_as_capacity() -> None:
    with pytest.raises(QuotaConfigurationError, match="字节数不能为负数"):
        QuotaPolicy().evaluate(
            used_bytes=-1,
            capacity_bytes=1_000,
            requested_bytes=0,
        )
