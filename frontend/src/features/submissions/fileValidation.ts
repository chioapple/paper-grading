export const MAX_SUBMISSION_FILES = 100;
export const MAX_SUBMISSION_FILE_BYTES = 20 * 1024 * 1024;

export type SubmissionFileErrorCode =
  | "file_empty"
  | "file_too_large"
  | "extension_unsupported";

export type SubmissionFileItem = {
  position: number;
  file: File;
  state: "selected" | "rejected";
  errorCode: SubmissionFileErrorCode | null;
};

export type SubmissionSelection = {
  selectionError: "too_many_files" | null;
  items: SubmissionFileItem[];
};

const SUPPORTED_EXTENSION = /\.(docx|pdf)$/i;

export function validateSubmissionSelection(files: File[]): SubmissionSelection {
  if (files.length > MAX_SUBMISSION_FILES) {
    return { selectionError: "too_many_files", items: [] };
  }

  return {
    selectionError: null,
    items: files.map((file, position) => {
      let errorCode: SubmissionFileErrorCode | null = null;
      if (file.size === 0) {
        errorCode = "file_empty";
      } else if (file.size > MAX_SUBMISSION_FILE_BYTES) {
        errorCode = "file_too_large";
      } else if (!SUPPORTED_EXTENSION.test(file.name)) {
        errorCode = "extension_unsupported";
      }
      return {
        position,
        file,
        state: errorCode ? "rejected" : "selected",
        errorCode,
      };
    }),
  };
}
