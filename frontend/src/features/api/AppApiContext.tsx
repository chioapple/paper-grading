import { createContext, useContext, type ReactNode } from "react";

import type { BrowserSession } from "../auth/AuthContext";

export type TeacherAccount = {
  id: string;
  email: string;
  display_name: string;
  status: "invited" | "active" | "disabled";
  invited_at: string | null;
};

export type InviteTeacherInput = {
  displayName: string;
  email: string;
};

export type ProviderType =
  | "deepseek"
  | "kimi"
  | "glm"
  | "openai"
  | "anthropic"
  | "gemini"
  | "openai_compatible";

export type ProviderConfig = {
  id: string;
  provider_type: ProviderType;
  name: string;
  base_url: string;
  api_key_configured: boolean;
  allowed_models: string[];
  default_model: string | null;
  timeout_seconds: string;
  max_concurrency: number;
  monthly_budget: string | null;
  status: "draft" | "enabled" | "disabled";
  configuration_tested: boolean;
  can_enable: boolean;
  tested_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProviderConfigInput = {
  providerType: ProviderType;
  name: string;
  baseUrl: string;
  apiKey?: string;
  allowedModels: string[];
  defaultModel: string;
  timeoutSeconds: string;
  maxConcurrency: number;
  monthlyBudget: string | null;
};

export type ProviderTestResult = {
  provider: ProviderConfig;
  available_models: string[];
};

export type AssignmentState = "draft" | "ready" | "archived";
export type RubricState = "draft" | "confirmed" | "superseded";
export type SubmissionState = "uploaded" | "parsing" | "ready" | "failed";
export type SubmissionMediaType =
  | "application/pdf"
  | "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export type RubricPointer = {
  id: string;
  version: number;
  status: RubricState;
};

export type AssignmentSummary = {
  id: string;
  title: string;
  status: AssignmentState;
  current_rubric_status: RubricState | null;
  current_rubric_version: number | null;
  current_draft_version: number | null;
  current_confirmed_version: number | null;
  current_draft: RubricPointer | null;
  current_confirmed: RubricPointer | null;
  created_at: string;
  updated_at: string;
};

export type RubricBand = {
  label: string;
  min_score: string;
  max_score: string;
  description: string;
};

export type RubricDimension = {
  id: string;
  name: string;
  description: string;
  max_score: string;
  bands: RubricBand[];
  evidence_requirements: string[];
};

export type RubricDeduction = {
  id: string;
  name: string;
  description: string;
  points: string;
};

export type StructuredRubric = {
  schema_version: 1;
  total_score: string;
  score_step: string;
  dimensions: RubricDimension[];
  deductions: RubricDeduction[];
};

export type RubricView = {
  id: string;
  assignment_id: string;
  version: number;
  status: RubricState;
  original_rubric: string;
  structured_rubric: StructuredRubric | null;
  total_score: string;
  score_step: string;
  provider_config_id: string | null;
  model: string | null;
  confirmed_at: string | null;
  created_at: string;
};

export type AssignmentDetail = AssignmentSummary & {
  instructions: string;
  rubric_versions: RubricView[];
};

export type AssignmentCreateInput = {
  title: string;
  instructions: string;
  originalRubric: string;
  totalScore: string;
  scoreStep: string;
};

export type AssignmentUpdateInput = {
  title: string;
  instructions: string;
};

export type TeacherProviderModels = {
  provider_id: string;
  provider_name: string;
  provider_type: ProviderType;
  allowed_models: string[];
  default_model: string;
};

export type RubricDraftInput = {
  originalRubric: string;
  totalScore: string;
  scoreStep: string;
};

export type SubmissionView = {
  id: string;
  assignment_id: string;
  original_filename: string;
  media_type: SubmissionMediaType;
  file_size_bytes: number;
  status: SubmissionState;
  error_code: string | null;
  created_at: string;
};

export type SubmissionUploadResult = {
  duplicate: boolean;
  submission: SubmissionView;
};

export type SubmissionDownload = {
  url: string;
  expires_in_seconds: number;
};

export type GradingJobCreated = {
  id: string;
  assignment_id: string;
  status: GradingJobState;
  total: number;
};

export type GradingItemState =
  | "queued"
  | "running"
  | "needs_review"
  | "completed"
  | "failed"
  | "cancelled";

export type GradingJobState = GradingItemState | "paused";

export type ReviewQueueItem = {
  id: string;
  submission_id: string;
  original_filename: string;
  position: number;
  status: GradingItemState;
  attempt_count: number;
  error_code: string | null;
  review_available: boolean;
  review_id: string | null;
  review_revision: number | null;
  review_status: "draft" | "confirmed" | null;
};

export type ReviewJobSummary = {
  id: string;
  assignment_id: string;
  assignment_title: string;
  model: string;
  status: GradingJobState;
  total: number;
  needs_review: number;
  completed: number;
  failed: number;
  items: ReviewQueueItem[];
  created_at: string;
  finished_at: string | null;
};

export type EvidenceQuote = { block_id: string; quote: string };

export type DimensionResult = {
  dimension_id: string;
  score: string;
  reason: string;
  evidence: EvidenceQuote[];
  revision_suggestions: string[];
};

export type DeductionResult = {
  deduction_id: string;
  applied: boolean;
  reason: string;
  evidence: EvidenceQuote[];
};

export type ReviewEvidence = EvidenceQuote & {
  target_type: "dimension" | "deduction";
  target_id: string;
};

export type ReviewDraftInput = {
  attempt_id: string;
  criteria: Array<Omit<DimensionResult, "evidence">>;
  deductions: Array<Omit<DeductionResult, "evidence">>;
  evidence: ReviewEvidence[];
  overall_feedback: string;
  change_reason: string | null;
};

export type ReviewDraft = ReviewDraftInput & {
  id: string;
  revision_number: number;
  status: "draft" | "confirmed";
  subtotal: string;
  deduction_total: string;
  final_score: string;
  confirmed_at: string | null;
};

export type DocumentBlock = {
  block_id: string;
  text: string;
  locator:
    | { kind: "pdf_text_block"; page: number; block: number; bbox: number[] }
    | { kind: "docx_paragraph"; paragraph: number }
    | {
        kind: "docx_table_paragraph";
        table: number;
        row: number;
        column: number;
        paragraph: number;
      };
};

export type ReviewDetail = {
  job_id: string;
  item_id: string;
  item_status: GradingItemState;
  assignment_id: string;
  assignment_title: string;
  assignment_instructions: string;
  rubric_version_id: string;
  rubric_version: number;
  rubric: StructuredRubric;
  submission_id: string;
  original_filename: string;
  document: {
    schema_version: "document-blocks.v1";
    parser_version: "1";
    media_type: SubmissionMediaType;
    page_count: number | null;
    character_count: number;
    blocks: DocumentBlock[];
  };
  attempt: {
    id: string;
    attempt_number: number;
    scoring_round: number;
    model: string;
    subtotal: string;
    deduction_total: string;
    total_score: string;
    dimensions: DimensionResult[];
    deductions: DeductionResult[];
    overall_feedback: string;
  };
  draft: ReviewDraft | null;
};

export type ReviewConfirmationRef = {
  item_id: string;
  review_id: string;
  revision_number: number;
};

export type ReviewConfirmationResult = {
  reviews: ReviewDraft[];
  completed_job_ids: string[];
};

export type ExportType = "draft" | "final";
export type ExportStatus = "queued" | "running" | "completed" | "failed";

export type ExportView = {
  id: string;
  assignment_id: string;
  assignment_title: string;
  grading_job_id: string;
  export_type: ExportType;
  status: ExportStatus;
  paper_count: number;
  source_counts: Record<string, number>;
  safe_filename: string | null;
  error_code: string | null;
  snapshot_at: string;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type ExportDownload = {
  download_url: string;
  expires_in_seconds: number;
  filename: string;
};

export interface AppApi {
  listExports(session: BrowserSession): Promise<ExportView[]>;
  createExport(
    session: BrowserSession,
    gradingJobId: string,
    exportType: ExportType,
    idempotencyKey: string,
  ): Promise<ExportView>;
  getExport(session: BrowserSession, exportId: string): Promise<ExportView>;
  createExportDownload(
    session: BrowserSession,
    exportId: string,
  ): Promise<ExportDownload>;
  listReviewJobs(session: BrowserSession): Promise<ReviewJobSummary[]>;
  getReview(
    session: BrowserSession,
    jobId: string,
    itemId: string,
  ): Promise<ReviewDetail>;
  saveReviewDraft(
    session: BrowserSession,
    jobId: string,
    itemId: string,
    input: ReviewDraftInput,
  ): Promise<ReviewDraft>;
  confirmReview(
    session: BrowserSession,
    jobId: string,
    itemId: string,
    input: ReviewDraftInput,
  ): Promise<ReviewConfirmationResult>;
  confirmReviewBatch(
    session: BrowserSession,
    jobId: string,
    reviews: ReviewConfirmationRef[],
  ): Promise<ReviewConfirmationResult>;
  regradeReview(
    session: BrowserSession,
    jobId: string,
    itemId: string,
  ): Promise<void>;
  retryGradingItem(
    session: BrowserSession,
    jobId: string,
    itemId: string,
  ): Promise<void>;
  listAssignments(session: BrowserSession): Promise<AssignmentSummary[]>;
  createAssignment(
    session: BrowserSession,
    input: AssignmentCreateInput,
  ): Promise<AssignmentDetail>;
  getAssignment(session: BrowserSession, assignmentId: string): Promise<AssignmentDetail>;
  updateAssignment(
    session: BrowserSession,
    assignmentId: string,
    input: AssignmentUpdateInput,
  ): Promise<AssignmentDetail>;
  listTeacherProviders(session: BrowserSession): Promise<TeacherProviderModels[]>;
  structureRubric(
    session: BrowserSession,
    assignmentId: string,
    rubricId: string,
    providerId: string,
  ): Promise<RubricView>;
  confirmRubric(
    session: BrowserSession,
    assignmentId: string,
    rubricId: string,
  ): Promise<AssignmentDetail>;
  updateAssignmentStatus(
    session: BrowserSession,
    assignmentId: string,
    action: "archive" | "restore",
  ): Promise<AssignmentDetail>;
  createRubricDraft(
    session: BrowserSession,
    assignmentId: string,
    input: RubricDraftInput,
  ): Promise<RubricView>;
  listSubmissions(
    session: BrowserSession,
    assignmentId: string,
  ): Promise<SubmissionView[]>;
  uploadSubmission(
    session: BrowserSession,
    assignmentId: string,
    file: File,
  ): Promise<SubmissionUploadResult>;
  createSubmissionDownload(
    session: BrowserSession,
    assignmentId: string,
    submissionId: string,
  ): Promise<SubmissionDownload>;
  createGradingJob(
    session: BrowserSession,
    assignmentId: string,
    submissionIds: string[],
    idempotencyKey: string,
  ): Promise<GradingJobCreated>;
  listTeachers(session: BrowserSession): Promise<TeacherAccount[]>;
  inviteTeacher(
    session: BrowserSession,
    input: InviteTeacherInput,
  ): Promise<TeacherAccount>;
  disableTeacher(session: BrowserSession, teacherId: string): Promise<void>;
  enableTeacher(session: BrowserSession, teacherId: string): Promise<void>;
  listProviders(session: BrowserSession): Promise<ProviderConfig[]>;
  createProvider(
    session: BrowserSession,
    input: ProviderConfigInput & { apiKey: string },
  ): Promise<ProviderConfig>;
  updateProvider(
    session: BrowserSession,
    providerId: string,
    input: ProviderConfigInput,
  ): Promise<ProviderConfig>;
  testProvider(session: BrowserSession, providerId: string): Promise<ProviderTestResult>;
  enableProvider(session: BrowserSession, providerId: string): Promise<ProviderConfig>;
  disableProvider(session: BrowserSession, providerId: string): Promise<ProviderConfig>;
}

const AppApiContext = createContext<AppApi | null>(null);

export function AppApiProvider({
  api,
  children,
}: {
  api: AppApi;
  children: ReactNode;
}) {
  return <AppApiContext.Provider value={api}>{children}</AppApiContext.Provider>;
}

// Provider 与 hook 同文件，避免公开内部 Context。
// eslint-disable-next-line react-refresh/only-export-components
export function useAppApi() {
  const api = useContext(AppApiContext);
  if (!api) {
    throw new Error("AppApiProvider 未挂载");
  }
  return api;
}
