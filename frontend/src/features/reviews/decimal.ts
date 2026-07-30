const SCALE_DIGITS = 4;
const SCALE = 10n ** BigInt(SCALE_DIGITS);
const DECIMAL_PATTERN = /^(0|[1-9][0-9]*)(?:\.([0-9]{1,4}))?$/;

export function parseDecimal(value: string): bigint | null {
  const match = DECIMAL_PATTERN.exec(value);
  if (!match) return null;
  const fraction = (match[2] ?? "").padEnd(SCALE_DIGITS, "0");
  return BigInt(match[1]) * SCALE + BigInt(fraction || "0");
}

export function formatDecimal(value: bigint): string {
  const safe = value < 0n ? 0n : value;
  const whole = safe / SCALE;
  const fraction = (safe % SCALE).toString().padStart(SCALE_DIGITS, "0");
  const trimmed = fraction.replace(/0+$/, "");
  return trimmed ? `${whole}.${trimmed}` : whole.toString();
}

export function calculateReviewTotal(
  scores: string[],
  deductions: Array<{ applied: boolean; points: string }>,
) {
  const parsedScores = scores.map(parseDecimal);
  const parsedDeductions = deductions.map(({ applied, points }) =>
    applied ? parseDecimal(points) : 0n,
  );
  if (
    parsedScores.some((value) => value === null) ||
    parsedDeductions.some((value) => value === null)
  ) {
    return null;
  }
  const subtotal = (parsedScores as bigint[]).reduce((sum, value) => sum + value, 0n);
  const deductionTotal = (parsedDeductions as bigint[]).reduce(
    (sum, value) => sum + value,
    0n,
  );
  return {
    subtotal: formatDecimal(subtotal),
    deductionTotal: formatDecimal(deductionTotal),
    finalScore: formatDecimal(subtotal - deductionTotal),
  };
}
