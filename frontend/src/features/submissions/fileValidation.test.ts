import { describe, expect, it } from "vitest";

import { validateSubmissionSelection } from "./fileValidation";

function buildFile(name: string, size = 10) {
  const file = new File([new Uint8Array(Math.min(size, 10))], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("submission file selection", () => {
  it("rejects the entire selection when it contains 101 files", () => {
    const files = Array.from({ length: 101 }, (_, index) =>
      buildFile(`essay-${index + 1}.docx`),
    );

    const result = validateSubmissionSelection(files);

    expect(result.selectionError).toBe("too_many_files");
    expect(result.items).toEqual([]);
  });

  it("keeps positions stable while rejecting empty, oversized, and unsupported files", () => {
    const result = validateSubmissionSelection([
      buildFile("valid.docx"),
      buildFile("empty.pdf", 0),
      buildFile("large.pdf", 20 * 1024 * 1024 + 1),
      buildFile("notes.txt"),
    ]);

    expect(result.selectionError).toBeNull();
    expect(result.items.map(({ position, state, errorCode }) => ({ position, state, errorCode })))
      .toEqual([
        { position: 0, state: "selected", errorCode: null },
        { position: 1, state: "rejected", errorCode: "file_empty" },
        { position: 2, state: "rejected", errorCode: "file_too_large" },
        { position: 3, state: "rejected", errorCode: "extension_unsupported" },
      ]);
  });
});
