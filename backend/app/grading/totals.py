"""只使用 Rubric 固定值计算最终总分。"""

from dataclasses import dataclass
from decimal import Decimal

from app.domain.grading import GradeResult
from app.domain.rubric import StructuredRubric


@dataclass(frozen=True, slots=True)
class GradeTotals:
    """后端确定性计算出的分数汇总。"""

    subtotal: Decimal
    deduction_total: Decimal
    total_score: Decimal


def calculate_grade_totals(
    result: GradeResult,
    rubric: StructuredRubric,
) -> GradeTotals:
    """忽略模型可能声称的总分，只按已校验分项和固定扣分计算。"""

    subtotal = sum(
        (dimension.score for dimension in result.dimensions),
        start=Decimal(0),
    )
    applied_ids = {deduction.deduction_id for deduction in result.deductions if deduction.applied}
    deduction_total = sum(
        (deduction.points for deduction in rubric.deductions if deduction.id in applied_ids),
        start=Decimal(0),
    )
    total_score = max(Decimal(0), subtotal - deduction_total)
    return GradeTotals(
        subtotal=subtotal,
        deduction_total=deduction_total,
        total_score=total_score,
    )
