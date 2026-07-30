import { describe, expect, it } from "vitest";

import { calculateReviewTotal, parseDecimal } from "./decimal";

describe("review decimals", () => {
  it("uses exact scaled integers instead of JavaScript floats", () => {
    expect(
      calculateReviewTotal(
        ["0.1", "0.2", "4.0000"],
        [{ applied: true, points: "0.3" }],
      ),
    ).toEqual({ subtotal: "4.3", deductionTotal: "0.3", finalScore: "4" });
  });

  it("rejects exponent notation, negatives, and more than four decimals", () => {
    expect(parseDecimal("1e2")).toBeNull();
    expect(parseDecimal("-1")).toBeNull();
    expect(parseDecimal("1.00001")).toBeNull();
  });
});
