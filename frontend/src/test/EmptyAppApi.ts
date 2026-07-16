import type {
  AppApi,
  AssignmentCreateInput,
  AssignmentDetail,
  ProviderConfig,
  ProviderConfigInput,
  ProviderTestResult,
  RubricDraftInput,
  RubricView,
  SubmissionDownload,
  SubmissionUploadResult,
  SubmissionView,
  TeacherAccount,
} from "../features/api/AppApiContext";
import type { BrowserSession } from "../features/auth/AuthContext";

export class EmptyAppApi implements AppApi {
  async listAssignments(_session: BrowserSession) {
    void _session;
    return [];
  }

  async createAssignment(
    _session: BrowserSession,
    _input: AssignmentCreateInput,
  ): Promise<AssignmentDetail> {
    void _session;
    void _input;
    throw new Error("本测试不使用作业创建");
  }

  async getAssignment(
    _session: BrowserSession,
    _assignmentId: string,
  ): Promise<AssignmentDetail> {
    void _session;
    void _assignmentId;
    throw new Error("本测试不使用作业详情");
  }

  async listTeacherProviders(_session: BrowserSession) {
    void _session;
    return [];
  }

  async structureRubric(
    _session: BrowserSession,
    _assignmentId: string,
    _rubricId: string,
    _providerId: string,
  ): Promise<RubricView> {
    void _session;
    void _assignmentId;
    void _rubricId;
    void _providerId;
    throw new Error("本测试不使用评分标准");
  }

  async confirmRubric(
    _session: BrowserSession,
    _assignmentId: string,
    _rubricId: string,
  ): Promise<AssignmentDetail> {
    void _session;
    void _assignmentId;
    void _rubricId;
    throw new Error("本测试不使用评分标准");
  }

  async updateAssignmentStatus(
    _session: BrowserSession,
    _assignmentId: string,
    _status: "draft" | "archived",
  ): Promise<AssignmentDetail> {
    void _session;
    void _assignmentId;
    void _status;
    throw new Error("本测试不使用作业状态");
  }

  async createRubricDraft(
    _session: BrowserSession,
    _assignmentId: string,
    _input: RubricDraftInput,
  ): Promise<RubricView> {
    void _session;
    void _assignmentId;
    void _input;
    throw new Error("本测试不使用评分标准修订");
  }

  async listSubmissions(
    _session: BrowserSession,
    _assignmentId: string,
  ): Promise<SubmissionView[]> {
    void _session;
    void _assignmentId;
    return [];
  }

  async uploadSubmission(
    _session: BrowserSession,
    _assignmentId: string,
    _file: File,
  ): Promise<SubmissionUploadResult> {
    void _session;
    void _assignmentId;
    void _file;
    throw new Error("本测试不使用论文上传");
  }

  async createSubmissionDownload(
    _session: BrowserSession,
    _assignmentId: string,
    _submissionId: string,
  ): Promise<SubmissionDownload> {
    void _session;
    void _assignmentId;
    void _submissionId;
    throw new Error("本测试不使用论文下载");
  }

  async listTeachers(_session: BrowserSession): Promise<TeacherAccount[]> {
    void _session;
    return [];
  }

  async inviteTeacher(
    _session: BrowserSession,
    _input: { displayName: string; email: string },
  ): Promise<TeacherAccount> {
    void _session;
    void _input;
    throw new Error("本测试不使用教师邀请");
  }

  async disableTeacher(_session: BrowserSession, _teacherId: string) {
    void _session;
    void _teacherId;
    return undefined;
  }

  async enableTeacher(_session: BrowserSession, _teacherId: string) {
    void _session;
    void _teacherId;
    return undefined;
  }

  async listProviders(_session: BrowserSession): Promise<ProviderConfig[]> {
    void _session;
    return [];
  }

  async createProvider(
    _session: BrowserSession,
    _input: ProviderConfigInput & { apiKey: string },
  ): Promise<ProviderConfig> {
    void _session;
    void _input;
    throw new Error("本测试不使用供应商配置");
  }

  async updateProvider(
    _session: BrowserSession,
    _providerId: string,
    _input: ProviderConfigInput,
  ): Promise<ProviderConfig> {
    void _session;
    void _providerId;
    void _input;
    throw new Error("本测试不使用供应商配置");
  }

  async testProvider(
    _session: BrowserSession,
    _providerId: string,
  ): Promise<ProviderTestResult> {
    void _session;
    void _providerId;
    throw new Error("本测试不使用供应商配置");
  }

  async enableProvider(
    _session: BrowserSession,
    _providerId: string,
  ): Promise<ProviderConfig> {
    void _session;
    void _providerId;
    throw new Error("本测试不使用供应商配置");
  }

  async disableProvider(
    _session: BrowserSession,
    _providerId: string,
  ): Promise<ProviderConfig> {
    void _session;
    void _providerId;
    throw new Error("本测试不使用供应商配置");
  }
}
