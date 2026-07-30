import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import { Icon } from "../../app/icons";
import {
  useAppApi,
  type ReviewConfirmationRef,
  type ReviewJobSummary,
} from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";
import { reviewCopy } from "../reviews/reviewCopy";

function statusLabel(
  status: ReviewJobSummary["status"],
  language: "zh" | "en",
) {
  const labels = {
    zh: {
      queued: "等待评分",
      running: "评分中",
      paused: "已暂停",
      needs_review: "待教师复核",
      completed: "已完成",
      failed: "失败",
      cancelled: "已取消",
    },
    en: {
      queued: "Queued",
      running: "Running",
      paused: "Paused",
      needs_review: "Teacher review",
      completed: "Completed",
      failed: "Failed",
      cancelled: "Cancelled",
    },
  } as const;
  return labels[language][status];
}

function itemErrorLabel(errorCode: string, language: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    provider_timeout: {
      zh: "模型服务响应超时",
      en: "The model service timed out",
    },
    provider_network_unavailable: {
      zh: "无法连接模型服务",
      en: "The model service is unreachable",
    },
    provider_base_url_unavailable: {
      zh: "模型服务地址不可用",
      en: "The model service address is unavailable",
    },
    provider_authentication_failed: {
      zh: "模型服务认证失败",
      en: "Model service authentication failed",
    },
    provider_balance_unavailable: {
      zh: "模型服务余额不足",
      en: "The model service balance is insufficient",
    },
    provider_model_unavailable: {
      zh: "批次固定模型不可用",
      en: "The batch model is unavailable",
    },
    provider_request_failed: {
      zh: "模型服务拒绝了评分请求",
      en: "The model service rejected the grading request",
    },
    grade_output_invalid: {
      zh: "模型评分结果不符合严格契约",
      en: "The model result failed strict validation",
    },
  };
  return labels[errorCode]?.[language] ?? errorCode;
}

export function GradingJobsPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { session } = useAuth();
  const api = useAppApi();
  const queryClient = useQueryClient();
  const copy = reviewCopy[language];
  const exportGrades = language === "zh" ? "导出成绩" : "Export grades";
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const jobsQuery = useQuery({
    queryKey: ["review-jobs"],
    enabled: Boolean(session),
    queryFn: () => {
      if (!session) throw new Error("登录会话不存在");
      return api.listReviewJobs(session);
    },
  });
  const batchMutation = useMutation({
    mutationFn: async ({
      jobId,
      reviews,
    }: {
      jobId: string;
      reviews: ReviewConfirmationRef[];
    }) => {
      if (!session) throw new Error("登录会话不存在");
      return api.confirmReviewBatch(session, jobId, reviews);
    },
    onSuccess: async () => {
      setError("");
      setMessage(copy.batchSuccess);
      await queryClient.invalidateQueries({ queryKey: ["review-jobs"] });
    },
    onError: () => {
      setMessage("");
      setError(copy.batchFailed);
    },
  });
  const regradeMutation = useMutation({
    mutationFn: async ({ jobId, itemId }: { jobId: string; itemId: string }) => {
      if (!session) throw new Error("登录会话不存在");
      return api.regradeReview(session, jobId, itemId);
    },
    onSuccess: async () => {
      setError("");
      setMessage(copy.regradeSubmitted);
      await queryClient.invalidateQueries({ queryKey: ["review-jobs"] });
    },
    onError: () => {
      setMessage("");
      setError(copy.regradeFailed);
    },
  });
  const retryFailedMutation = useMutation({
    mutationFn: async ({ jobId, itemId }: { jobId: string; itemId: string }) => {
      if (!session) throw new Error("登录会话不存在");
      return api.retryGradingItem(session, jobId, itemId);
    },
    onSuccess: async () => {
      setError("");
      setMessage(copy.retryFailedSubmitted);
      await queryClient.invalidateQueries({ queryKey: ["review-jobs"] });
    },
    onError: () => {
      setMessage("");
      setError(copy.retryFailedFailed);
    },
  });
  const jobs = jobsQuery.data ?? [];
  const loadError = jobsQuery.error instanceof ApiRequestError
    ? jobsQuery.error.status === 401
      ? copy.loadUnauthorized
      : jobsQuery.error.status >= 500
        ? copy.loadServerFailed
        : copy.loadFailed
    : copy.loadFailed;

  return (
    <div className="page review-jobs-page">
      <header className="stage6-page-header">
        <div>
          <h1>{copy.jobsTitle}</h1>
          <p>{copy.jobsIntro}</p>
        </div>
      </header>

      {jobsQuery.isPending ? <p className="table-empty">{copy.loading}</p> : null}
      {jobsQuery.isError ? (
        <div className="form-message form-message--error" role="alert">
          <span>{loadError}</span>
          <button
            className="stage6-row-link"
            onClick={() => void jobsQuery.refetch()}
            type="button"
          >
            {copy.retryLoad}
          </button>
        </div>
      ) : null}
      {message ? <p className="form-message form-message--success">{message}</p> : null}
      {error ? (
        <p className="form-message form-message--error" role="alert">
          {error}
        </p>
      ) : null}
      {!jobsQuery.isPending && !jobsQuery.isError && jobs.length === 0 ? (
        <section className="empty-state">
          <div className="empty-state__icon">
            <Icon name="clipboard" />
          </div>
          <h2>{copy.emptyTitle}</h2>
          <p>{copy.emptyBody}</p>
        </section>
      ) : null}

      <div className="review-job-list">
        {jobs.map((job) => {
          const pending = job.items.filter((item) => item.status === "needs_review");
          const saved = pending.filter(
            (item) => item.review_id && item.review_revision && item.review_status === "draft",
          );
          const canBatch = pending.length > 0 && saved.length === pending.length;
          const references: ReviewConfirmationRef[] = saved.map((item) => ({
            item_id: item.id,
            review_id: item.review_id as string,
            revision_number: item.review_revision as number,
          }));
          return (
            <section className="review-job-card" key={job.id}>
              <header className="review-job-card__header">
                <div>
                  <span className="review-status-pill">{statusLabel(job.status, language)}</span>
                  <h2>{job.assignment_title}</h2>
                  <p>
                    {copy.model}: {job.model}
                  </p>
                </div>
                <div className="review-job-card__progress" aria-label={copy.progress}>
                  <strong>
                    {job.completed}/{job.total}
                  </strong>
                  <span>{copy.completed}</span>
                </div>
              </header>
              <div className="review-progress-track" aria-hidden="true">
                <span style={{ width: `${(job.completed / job.total) * 100}%` }} />
              </div>
              <div className="review-job-stats">
                <span>{copy.needsReview}: {job.needs_review}</span>
                <span>{copy.completed}: {job.completed}</span>
                <span>{copy.failed}: {job.failed}</span>
              </div>
              <ul className="review-paper-list" aria-label={copy.papers}>
                {job.items.map((item) => (
                  <li key={item.id}>
                    <div>
                      <strong>{item.original_filename}</strong>
                      <span>{statusLabel(item.status, language)}</span>
                      {item.error_code ? (
                        <small className="submission-error">
                          {itemErrorLabel(item.error_code, language)}
                        </small>
                      ) : null}
                    </div>
                    {item.status === "failed" ? (
                      <button
                        className="stage6-row-link"
                        disabled={retryFailedMutation.isPending}
                        onClick={() => {
                          if (window.confirm(copy.retryFailedPrompt)) {
                            retryFailedMutation.mutate({ jobId: job.id, itemId: item.id });
                          }
                        }}
                        type="button"
                      >
                        {retryFailedMutation.isPending
                          ? copy.retryingFailedItem
                          : copy.retryFailedItem}
                      </button>
                    ) : item.status === "needs_review" && !item.review_available ? (
                      <button
                        className="stage6-row-link"
                        disabled={regradeMutation.isPending}
                        onClick={() => {
                          if (window.confirm(copy.regradePrompt)) {
                            regradeMutation.mutate({ jobId: job.id, itemId: item.id });
                          }
                        }}
                        type="button"
                      >
                        {regradeMutation.isPending ? copy.regrading : copy.regrade}
                      </button>
                    ) : item.status === "needs_review" || item.status === "completed" ? (
                      <Link
                        className="stage6-row-link"
                        to={`/grading-jobs/${job.id}/reviews/${item.id}`}
                      >
                        {copy.open}
                      </Link>
                    ) : (
                      <span className="review-unavailable">{copy.unavailable}</span>
                    )}
                  </li>
                ))}
              </ul>
              <div className="review-job-card__actions">
                <Link
                  className="secondary-button"
                  to={`/exports?jobId=${job.id}`}
                >
                  <Icon name="download" /> {exportGrades}
                </Link>
                <button
                  className="primary-button"
                  disabled={!canBatch || batchMutation.isPending}
                  onClick={() => {
                    if (window.confirm(copy.batchConfirmPrompt)) {
                      batchMutation.mutate({ jobId: job.id, reviews: references });
                    }
                  }}
                  title={canBatch ? undefined : copy.batchUnavailable}
                  type="button"
                >
                  {batchMutation.isPending ? copy.confirming : copy.batchConfirm}
                </button>
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
