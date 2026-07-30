import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../../app/App";
import {
  AppApiProvider,
  type ReviewConfirmationResult,
  type ReviewDetail,
  type ReviewDraft,
  type ReviewDraftInput,
  type ReviewJobSummary,
} from "../api/AppApiContext";
import { AuthProvider, type AuthClient } from "../auth/AuthContext";
import { ApiRequestError } from "../api/httpAppApi";
import { EmptyAppApi } from "../../test/EmptyAppApi";

const JOB_ID = "22222222-2222-4222-8222-222222222222";
const ITEM_ID = "33333333-3333-4333-8333-333333333333";
const ITEM_TWO_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const ATTEMPT_ID = "77777777-7777-4777-8777-777777777777";
const REVIEW_ID = "88888888-8888-4888-8888-888888888888";
const session = { accessToken: "teacher-token" };

class TestAuthClient implements AuthClient {
  async getSession() {
    return session;
  }
  subscribe() {
    return () => undefined;
  }
  async signIn() {
    return session;
  }
  async requestPasswordReset() {
    return undefined;
  }
  async consumeRedirect() {
    return session;
  }
  async updatePassword() {
    return undefined;
  }
  async signOut() {
    return undefined;
  }
}

function job(): ReviewJobSummary {
  return {
    id: JOB_ID,
    assignment_id: "55555555-5555-4555-8555-555555555555",
    assignment_title: "Argumentative essay",
    model: "deepseek-v4-pro",
    status: "needs_review",
    total: 2,
    needs_review: 2,
    completed: 0,
    failed: 0,
    items: [
      {
        id: ITEM_ID,
        submission_id: "44444444-4444-4444-8444-444444444444",
        original_filename: "essay-01.pdf",
        position: 0,
        status: "needs_review",
        attempt_count: 1,
        error_code: null,
        review_available: true,
        review_id: REVIEW_ID,
        review_revision: 1,
        review_status: "draft",
      },
      {
        id: ITEM_TWO_ID,
        submission_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        original_filename: "essay-02.pdf",
        position: 1,
        status: "needs_review",
        attempt_count: 1,
        error_code: null,
        review_available: true,
        review_id: null,
        review_revision: null,
        review_status: null,
      },
    ],
    created_at: "2026-07-19T08:00:00Z",
    finished_at: null,
  };
}

function detail(): ReviewDetail {
  return {
    job_id: JOB_ID,
    item_id: ITEM_ID,
    item_status: "needs_review",
    assignment_id: "55555555-5555-4555-8555-555555555555",
    assignment_title: "Argumentative essay",
    assignment_instructions: "Discuss whether public transport should be free.",
    rubric_version_id: "66666666-6666-4666-8666-666666666666",
    rubric_version: 1,
    rubric: {
      schema_version: 1,
      total_score: "10",
      score_step: "1",
      dimensions: [
        {
          id: "argument",
          name: "Argument",
          description: "Quality of the argument.",
          max_score: "10",
          bands: [
            {
              label: "Full range",
              min_score: "0",
              max_score: "10",
              description: "Use the full range.",
            },
          ],
          evidence_requirements: ["Quote the claim."],
        },
      ],
      deductions: [
        {
          id: "missing_title",
          name: "Missing title",
          description: "Deduct one point when the title is absent.",
          points: "1",
        },
      ],
    },
    submission_id: "44444444-4444-4444-8444-444444444444",
    original_filename: "essay-01.pdf",
    document: {
      schema_version: "document-blocks.v1",
      parser_version: "1",
      media_type: "application/pdf",
      page_count: 1,
      character_count: 112,
      blocks: [
        {
          block_id: "b000001",
          text: "Public transport should be free because it reduces traffic.",
          locator: {
            kind: "pdf_text_block",
            page: 1,
            block: 1,
            bbox: [10, 20, 300, 40],
          },
        },
        {
          block_id: "b000002",
          text: "This policy makes cities cleaner and easier to reach.",
          locator: {
            kind: "pdf_text_block",
            page: 1,
            block: 2,
            bbox: [10, 50, 300, 70],
          },
        },
      ],
    },
    attempt: {
      id: ATTEMPT_ID,
      attempt_number: 1,
      scoring_round: 1,
      model: "deepseek-v4-pro",
      subtotal: "8",
      deduction_total: "1",
      total_score: "7",
      dimensions: [
        {
          dimension_id: "argument",
          score: "8",
          reason: "The claim is clear.",
          evidence: [{ block_id: "b000001", quote: "it reduces traffic" }],
          revision_suggestions: ["Explain the causal link."],
        },
      ],
      deductions: [
        {
          deduction_id: "missing_title",
          applied: true,
          reason: "The title is absent.",
          evidence: [],
        },
      ],
      overall_feedback: "A clear response with room for fuller explanation.",
    },
    draft: null,
  };
}

function confirmedDraft(input: ReviewDraftInput): ReviewDraft {
  return {
    ...input,
    id: REVIEW_ID,
    revision_number: 1,
    status: "confirmed",
    subtotal: "8",
    deduction_total: "1",
    final_score: "7",
    confirmed_at: "2026-07-19T09:00:00Z",
  };
}

class Stage11Api extends EmptyAppApi {
  savedInput: ReviewDraftInput | null = null;
  regradeRequests: Array<{ jobId: string; itemId: string }> = [];
  retryRequests: Array<{ jobId: string; itemId: string }> = [];

  async listReviewJobs() {
    return [job()];
  }

  async getReview(
    _session: typeof session,
    _jobId: string,
    _itemId: string,
  ) {
    void _session;
    void _jobId;
    void _itemId;
    return detail();
  }

  async saveReviewDraft(
    _session: typeof session,
    _jobId: string,
    _itemId: string,
    input: ReviewDraftInput,
  ) {
    this.savedInput = input;
    return { ...confirmedDraft(input), status: "draft" as const, confirmed_at: null };
  }

  async confirmReview(
    _session: typeof session,
    _jobId: string,
    _itemId: string,
    input: ReviewDraftInput,
  ): Promise<ReviewConfirmationResult> {
    return { reviews: [confirmedDraft(input)], completed_job_ids: [JOB_ID] };
  }

  async regradeReview(
    _session: typeof session,
    jobId: string,
    itemId: string,
  ) {
    this.regradeRequests.push({ jobId, itemId });
    return { id: jobId } as never;
  }

  async retryGradingItem(
    _session: typeof session,
    jobId: string,
    itemId: string,
  ) {
    this.retryRequests.push({ jobId, itemId });
  }
}

class FailedItemJobsApi extends Stage11Api {
  override async listReviewJobs() {
    const value = job();
    value.status = "failed";
    value.needs_review = 0;
    value.failed = 1;
    value.items[0] = {
      ...value.items[0],
      status: "failed",
      error_code: "provider_timeout",
      review_available: false,
      review_id: null,
      review_revision: null,
      review_status: null,
    };
    return [value];
  }
}

class FailedAttemptJobsApi extends Stage11Api {
  override async listReviewJobs() {
    const value = job();
    value.items[1] = { ...value.items[1], review_available: false };
    return [value];
  }
}

class RetryJobsApi extends Stage11Api {
  listAttempts = 0;

  override async listReviewJobs() {
    this.listAttempts += 1;
    if (this.listAttempts === 1) {
      throw new ApiRequestError("服务器拒绝了请求", 500);
    }
    return [job()];
  }
}

class FailedReviewDetailApi extends Stage11Api {
  override async getReview(
    _session: typeof session,
    _jobId: string,
    _itemId: string,
  ): Promise<ReviewDetail> {
    void _session;
    void _jobId;
    void _itemId;
    throw new ApiRequestError("复核任务不存在", 404, "review_not_found");
  }
}

class SwitchingReviewApi extends Stage11Api {
  override async getReview(
    _session: typeof session,
    _jobId: string,
    itemId: string,
  ): Promise<ReviewDetail> {
    const value = detail();
    if (itemId === ITEM_TWO_ID) {
      value.item_id = ITEM_TWO_ID;
      value.submission_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
      value.original_filename = "essay-02.pdf";
    }
    return value;
  }
}

function renderStage11(path: string, api = new Stage11Api()) {
  const account = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "teacher@example.com",
    display_name: "张老师",
    role: "teacher" as const,
    status: "active" as const,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <AppApiProvider api={api}>
      <AuthProvider
        authClient={new TestAuthClient()}
        completeInvite={async () => account}
        loadAccount={async () => account}
      >
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </AuthProvider>
    </AppApiProvider>,
  );
  return api;
}

function textNodeContaining(root: Element, text: string): Text {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    if (node.textContent?.includes(text)) return node as Text;
    node = walker.nextNode();
  }
  throw new Error(`找不到文本节点: ${text}`);
}

describe("stage 11 teacher review", () => {
  beforeEach(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists the teacher's batches and papers without manual UUID input", async () => {
    renderStage11("/grading-jobs");

    expect(await screen.findByRole("heading", { name: "批改任务" })).toBeVisible();
    expect(await screen.findByText("Argumentative essay")).toBeVisible();
    expect(screen.getByText("essay-01.pdf")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: /UUID/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认全部已保存草稿" })).toBeDisabled();
  });

  it("shows a safe server error and lets the teacher retry the jobs request", async () => {
    const api = new RetryJobsApi();
    renderStage11("/grading-jobs", api);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "服务端暂时无法读取批次，请确认 API 已更新并正常运行。",
    );
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByText("Argumentative essay")).toBeVisible();
    expect(api.listAttempts).toBe(2);
  });

  it("offers original-model regrade when a pending item has no successful result", async () => {
    const api = new FailedAttemptJobsApi();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderStage11("/grading-jobs", api);

    fireEvent.click(await screen.findByRole("button", { name: "使用原模型重评" }));

    await waitFor(() => {
      expect(api.regradeRequests).toEqual([{ jobId: JOB_ID, itemId: ITEM_TWO_ID }]);
    });
  });

  it("lets the teacher retry a failed grading item with a cost warning", async () => {
    const api = new FailedItemJobsApi();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderStage11("/grading-jobs", api);

    fireEvent.click(await screen.findByRole("button", { name: "重试评分" }));

    expect(screen.getByText("模型服务响应超时")).toBeVisible();

    await waitFor(() => {
      expect(api.retryRequests).toEqual([{ jobId: JOB_ID, itemId: ITEM_ID }]);
    });
    expect(window.confirm).toHaveBeenCalledWith(
      "确认重试这篇失败论文？这会使用批次固定模型并产生新的模型费用。",
    );
  });

  it("shows the review detail failure instead of an endless loading state", async () => {
    renderStage11(
      `/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`,
      new FailedReviewDetailApi(),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法加载复核任务");
    expect(screen.queryByText("正在加载复核任务")).not.toBeInTheDocument();
  });

  it("requires an explicit model cost confirmation before regrading from the review page", async () => {
    const api = new Stage11Api();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderStage11(`/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`, api);

    fireEvent.click(await screen.findByRole("button", { name: "使用原模型重评" }));

    expect(window.confirm).toHaveBeenCalledWith(
      "该论文没有可复核的成功模型结果。确认使用批次固定的原模型重评？这会产生新的模型费用。",
    );
    await waitFor(() => {
      expect(api.regradeRequests).toEqual([{ jobId: JOB_ID, itemId: ITEM_ID }]);
    });
  });

  it("does not regrade when the teacher cancels the model cost confirmation", async () => {
    const api = new Stage11Api();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderStage11(`/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`, api);

    fireEvent.click(await screen.findByRole("button", { name: "使用原模型重评" }));

    expect(api.regradeRequests).toEqual([]);
  });

  it("does not open a queue item without a successful review result", async () => {
    renderStage11(
      `/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`,
      new FailedAttemptJobsApi(),
    );

    const filename = await screen.findByText("essay-02.pdf");
    const queueItem = filename.closest("li");
    expect(queueItem).not.toBeNull();
    expect(within(queueItem as HTMLLIElement).getByText("尚不可复核")).toBeVisible();
    expect(within(queueItem as HTMLLIElement).queryByRole("link")).not.toBeInTheDocument();
  });

  it("does not carry a submitted regrade state into the next queue item", async () => {
    const api = new SwitchingReviewApi();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderStage11(`/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`, api);

    fireEvent.click(await screen.findByRole("button", { name: "使用原模型重评" }));
    await waitFor(() => {
      expect(api.regradeRequests).toEqual([{ jobId: JOB_ID, itemId: ITEM_ID }]);
    });
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeDisabled();

    fireEvent.click(screen.getByRole("link", { name: /essay-02\.pdf/ }));

    expect(await screen.findByRole("heading", { name: "essay-02.pdf" })).toBeVisible();
    expect(screen.getByRole("button", { name: "保存草稿" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "使用原模型重评" })).toBeEnabled();
  });

  it("supports keyboard tabs and bilingual workbench labels", async () => {
    renderStage11(`/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`);

    const paperTab = await screen.findByRole("tab", { name: "论文正文" });
    paperTab.focus();
    fireEvent.keyDown(paperTab, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "评分复核" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "Switch to English" }));
    expect(screen.getByRole("tab", { name: "Grade review" })).toBeVisible();
    expect(document.documentElement.lang).toBe("en");
  });

  it("preserves block id and exact selected quote, then focuses evidence", async () => {
    const api = renderStage11(`/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`);
    await waitFor(() =>
      expect(document.querySelector('[data-block-id="b000001"]')).not.toBeNull(),
    );
    const block = document.querySelector<HTMLElement>('[data-block-id="b000001"]');
    const node = textNodeContaining(block as HTMLElement, "Public transport");
    const start = node.textContent?.indexOf("Public transport") ?? -1;
    const range = document.createRange();
    range.setStart(node, start);
    range.setEnd(node, start + "Public transport".length);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);

    fireEvent.click(screen.getByRole("button", { name: "添加当前选中文本" }));
    fireEvent.click(screen.getByRole("button", { name: /b000001: “Public transport”/ }));
    await waitFor(() => expect(document.activeElement).toBe(block));
    fireEvent.click(screen.getByRole("button", { name: "保存草稿" }));

    await waitFor(() => expect(api.savedInput).not.toBeNull());
    expect(api.savedInput?.evidence.at(-1)).toEqual({
      target_type: "dimension",
      target_id: "argument",
      block_id: "b000001",
      quote: "Public transport",
    });

  });

  it("rejects a selection that crosses text blocks", async () => {
    renderStage11(`/grading-jobs/${JOB_ID}/reviews/${ITEM_ID}`);
    await waitFor(() =>
      expect(document.querySelectorAll<HTMLElement>("[data-block-id]")).toHaveLength(2),
    );
    const blocks = Array.from(
      document.querySelectorAll<HTMLElement>("[data-block-id]"),
    );
    const startNode = textNodeContaining(blocks[0], "Public transport");
    const endNode = textNodeContaining(blocks[1], "This policy");
    const range = document.createRange();
    range.setStart(startNode, 0);
    range.setEnd(endNode, "This policy".length);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);

    fireEvent.click(screen.getByRole("button", { name: "添加当前选中文本" }));

    expect(screen.getByRole("alert")).toHaveTextContent("证据不能跨越多个文本块");
  });
});
