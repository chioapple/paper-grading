"""使用整数容量计算可配置的资源配额状态。"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

QuotaState = Literal["ok", "warning", "blocked"]


class QuotaConfigurationError(ValueError):
    """容量或阈值不能形成可靠判断。"""


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    """一次增长请求在当前容量下的可观察结果。"""

    state: QuotaState
    used_bytes: int
    requested_bytes: int
    projected_bytes: int
    capacity_bytes: int


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """70% 提醒、85% 阻断；阈值可由调用方覆盖。"""

    warning_ratio: Decimal = Decimal("0.70")
    hard_limit_ratio: Decimal = Decimal("0.85")

    def __post_init__(self) -> None:
        if not Decimal(0) < self.warning_ratio < self.hard_limit_ratio <= Decimal(1):
            raise QuotaConfigurationError("配额阈值必须满足 0 < 提醒阈值 < 阻断阈值 <= 1")

    def evaluate(
        self,
        *,
        used_bytes: int,
        capacity_bytes: int,
        requested_bytes: int,
    ) -> QuotaDecision:
        if capacity_bytes <= 0:
            raise QuotaConfigurationError("容量必须大于零")
        if used_bytes < 0 or requested_bytes < 0:
            raise QuotaConfigurationError("使用量和请求字节数不能为负数")
        projected = used_bytes + requested_bytes
        ratio = Decimal(projected) / Decimal(capacity_bytes)
        if ratio >= self.hard_limit_ratio:
            state: QuotaState = "blocked"
        elif ratio >= self.warning_ratio:
            state = "warning"
        else:
            state = "ok"
        return QuotaDecision(
            state=state,
            used_bytes=used_bytes,
            requested_bytes=requested_bytes,
            projected_bytes=projected,
            capacity_bytes=capacity_bytes,
        )
