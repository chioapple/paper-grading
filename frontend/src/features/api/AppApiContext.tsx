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

export interface AppApi {
  listAssignments(session: BrowserSession): Promise<AssignmentSummary[]>;
  createAssignment(
    session: BrowserSession,
    input: AssignmentCreateInput,
  ): Promise<AssignmentDetail>;
  getAssignment(session: BrowserSession, assignmentId: string): Promise<AssignmentDetail>;
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
    status: "draft" | "archived",
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
