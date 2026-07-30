import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import { Icon } from "../../app/icons";
import { useAppApi, type ExportType } from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";
import { exportsCopy } from "./exportsCopy";

function exportFailureLabel(errorCode: string | null, language: "zh" | "en") {
  const labels: Record<string, { zh: string; en: string }> = {
    export_storage_failed: {
      zh: "Excel 文件未能安全保存，请重新创建导出。",
      en: "The Excel file could not be stored safely. Create a new export.",
    },
    export_snapshot_invalid: {
      zh: "冻结的导出内容未通过完整性检查，请返回批改任务重新检查。",
      en: "The frozen export content failed validation. Return to the grading job and review it.",
    },
    export_score_invalid: {
      zh: "冻结成绩包含无效数值，请返回批改任务重新检查。",
      en: "The frozen export contains an invalid score. Return to the grading job and review it.",
    },
    export_cell_text_invalid: {
      zh: "导出内容包含 Excel 无法安全保存的文本，请检查教师反馈和文件名。",
      en: "Some text cannot be stored safely in Excel. Check teacher feedback and file names.",
    },
    export_cell_text_too_long: {
      zh: "导出内容超过 Excel 单元格限制，请缩短对应教师反馈后重新创建。",
      en: "Some content exceeds Excel's cell limit. Shorten the related teacher feedback and create a new export.",
    },
    export_workbook_invalid: {
      zh: "生成的工作簿未通过完整性检查，请重新创建导出。",
      en: "The workbook failed its integrity check. Create a new export.",
    },
    export_workbook_failed: {
      zh: "Excel 文件生成失败，请重新创建导出。",
      en: "The Excel file could not be generated. Create a new export.",
    },
    export_workbook_timeout: {
      zh: "Excel 文件生成连续超时，请重新创建导出。",
      en: "Excel generation timed out repeatedly. Create a new export.",
    },
    export_worker_lost: {
      zh: "导出 Worker 多次中断，请重新创建导出。",
      en: "The export worker stopped repeatedly. Create a new export.",
    },
    export_completion_failed: {
      zh: "Excel 文件未能安全完成登记，请重新创建导出。",
      en: "The Excel file could not be registered safely. Create a new export.",
    },
  };
  return labels[errorCode ?? ""]?.[language]
    ?? (language === "zh"
      ? "导出未完成，请返回批改任务检查状态后重新创建。"
      : "The export did not finish. Check the grading job before creating a new export.");
}

export function ExportsPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { account, session } = useAuth();
  const api = useAppApi();
  const queryClient = useQueryClient();
  const copy = exportsCopy[language];
  const [searchParams] = useSearchParams();
  const [exportType, setExportType] = useState<ExportType>("draft");
  const [showQueuedMessage, setShowQueuedMessage] = useState(false);
  const [error, setError] = useState("");
  const [downloadingId, setDownloadingId] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const requestRef = useRef<{ fingerprint: string; key: string } | null>(null);
  const selectedJobId = searchParams.get("jobId") ?? "";
  const exportsQuery = useQuery({
    queryKey: ["exports", account?.id],
    enabled: Boolean(session),
    queryFn: () => {
      if (!session) throw new Error("登录会话不存在");
      return api.listExports(session);
    },
    refetchInterval: (query) => query.state.data?.some(
      (item) => item.status === "queued" || item.status === "running",
    ) ? 1_500 : false,
  });
  const jobsQuery = useQuery({
    queryKey: ["review-jobs", account?.id],
    enabled: Boolean(session && selectedJobId),
    queryFn: () => {
      if (!session) throw new Error("登录会话不存在");
      return api.listReviewJobs(session);
    },
  });
  const exports = exportsQuery.data ?? [];
  const loadError = exportsQuery.error instanceof ApiRequestError
    && exportsQuery.error.status === 401
    ? copy.loadUnauthorized
    : copy.loadFailed;
  const selectedJob = jobsQuery.data?.find((job) => job.id === selectedJobId);
  const jobLoadError = jobsQuery.error instanceof ApiRequestError
    && jobsQuery.error.status === 401
    ? copy.createUnauthorized
    : copy.createNotFound;
  const unconfirmedCount = selectedJob?.items.filter(
    (item) => item.status !== "completed" || item.review_status !== "confirmed",
  ).length ?? 0;
  const finalAvailable = Boolean(
    selectedJob
      && selectedJob.status === "completed"
      && unconfirmedCount === 0
      && selectedJob.items.length === selectedJob.total,
  );
  const draftAvailable = Boolean(
    selectedJob
      && selectedJob.items.length === selectedJob.total
      && selectedJob.items.every(
        (item) => (item.status === "needs_review" || item.status === "completed")
          && item.review_available,
      ),
  );
  const sourceCounts = selectedJob?.items.reduce(
    (counts, item) => {
      if (item.review_status === "confirmed") counts.confirmed += 1;
      else if (item.review_status === "draft") counts.draft += 1;
      else if (item.review_available) counts.ai += 1;
      return counts;
    },
    { ai: 0, draft: 0, confirmed: 0 },
  ) ?? { ai: 0, draft: 0, confirmed: 0 };
  const createMutation = useMutation({
    mutationFn: async ({
      jobId,
      type,
      idempotencyKey,
    }: {
      jobId: string;
      type: ExportType;
      idempotencyKey: string;
    }) => {
      if (!session) throw new Error("登录会话不存在");
      return api.createExport(session, jobId, type, idempotencyKey);
    },
    onSuccess: async () => {
      requestRef.current = null;
      setError("");
      setShowQueuedMessage(true);
      await queryClient.invalidateQueries({ queryKey: ["exports", account?.id] });
    },
    onError: (actionError) => {
      setShowQueuedMessage(false);
      if (actionError instanceof ApiRequestError) {
        if (actionError.status === 401) {
          setError(copy.createUnauthorized);
          return;
        }
        if (actionError.status === 403 || actionError.status === 404) {
          setError(copy.createNotFound);
          return;
        }
        if (actionError.status === 409) {
          setError(copy.createConflict);
          return;
        }
      }
      setError(copy.createFailed);
    },
  });

  function changeExportType(next: ExportType) {
    setExportType(next);
    requestRef.current = null;
    setShowQueuedMessage(false);
    setError("");
  }

  function createExport() {
    if (!selectedJob || createMutation.isPending) return;
    const fingerprint = `${selectedJob.id}:${exportType}`;
    const idempotencyKey = requestRef.current?.fingerprint === fingerprint
      ? requestRef.current.key
      : `export-${globalThis.crypto.randomUUID()}`;
    requestRef.current = { fingerprint, key: idempotencyKey };
    createMutation.mutate({
      jobId: selectedJob.id,
      type: exportType,
      idempotencyKey,
    });
  }

  async function downloadExport(exportId: string) {
    if (!session || downloadingId) return;
    setDownloadingId(exportId);
    setDownloadError("");
    try {
      const result = await api.createExportDownload(session, exportId);
      const link = document.createElement("a");
      link.href = result.download_url;
      link.download = result.filename;
      link.rel = "noopener noreferrer";
      link.click();
    } catch {
      setDownloadError(copy.downloadFailed);
    } finally {
      setDownloadingId("");
    }
  }
  const locale = language === "zh" ? "zh-CN" : "en";

  return (
    <div className="page exports-page">
      <header className="stage6-page-header">
        <div>
          <h1>{copy.title}</h1>
          <p>{copy.intro}</p>
        </div>
      </header>

      <section className="export-create-panel" aria-labelledby="export-create-title">
        <h2 id="export-create-title">{copy.create}</h2>
        {!selectedJobId ? (
          <div className="export-create-empty">
            <p>{copy.chooseJob}</p>
            <Link className="secondary-button" to="/grading-jobs">{copy.backToJobs}</Link>
          </div>
        ) : null}
        {selectedJobId && jobsQuery.isPending ? (
          <p className="table-empty" role="status">{copy.loading}</p>
        ) : null}
        {selectedJobId && !jobsQuery.isPending && (jobsQuery.isError || !selectedJob) ? (
          <div className="export-create-empty form-message form-message--error" role="alert">
            <p>{jobLoadError}</p>
            <Link className="secondary-button" to="/grading-jobs">{copy.backToJobs}</Link>
          </div>
        ) : null}
        {selectedJob ? (
          <div className="export-create-content">
            <header>
              <div>
                <h3>{selectedJob.assignment_title}</h3>
                <p>{copy.paperCount(selectedJob.total)}</p>
                <p className="export-source-range">
                  {copy.sourceRange(sourceCounts.ai, sourceCounts.draft, sourceCounts.confirmed)}
                </p>
              </div>
              <span>{selectedJob.id.slice(0, 8)}</span>
            </header>
            <fieldset className="export-type-options">
              <legend>{copy.exportType}</legend>
              <label>
                <input
                  aria-describedby={draftAvailable ? undefined : "draft-export-help"}
                  checked={exportType === "draft"}
                  disabled={!draftAvailable}
                  name="export-type"
                  onChange={() => changeExportType("draft")}
                  type="radio"
                />
                <span><strong>{copy.draftGrade}</strong><small>{copy.draftHelp}</small></span>
              </label>
              <label>
                <input
                  aria-describedby={finalAvailable ? undefined : "final-export-help"}
                  checked={exportType === "final"}
                  disabled={!finalAvailable}
                  name="export-type"
                  onChange={() => changeExportType("final")}
                  type="radio"
                />
                <span><strong>{copy.finalGrade}</strong><small>{copy.finalHelp}</small></span>
              </label>
            </fieldset>
            {!finalAvailable ? (
              <p className="export-type-warning" id="final-export-help">
                {copy.finalBlocked(unconfirmedCount)}
              </p>
            ) : null}
            {!draftAvailable ? (
              <p className="export-type-warning" id="draft-export-help">{copy.draftBlocked}</p>
            ) : null}
            {showQueuedMessage ? (
              <p className="form-message form-message--success" role="status">{copy.createQueued}</p>
            ) : null}
            {error ? <p className="form-message form-message--error" role="alert">{error}</p> : null}
            <button
              className="primary-button export-create-button"
              disabled={
                createMutation.isPending
                || (exportType === "draft" ? !draftAvailable : !finalAvailable)
              }
              onClick={createExport}
              type="button"
            >
              {createMutation.isPending
                ? copy.generating
                : exportType === "draft"
                  ? copy.generateDraft
                  : copy.generateFinal}
            </button>
          </div>
        ) : null}
      </section>

      <section className="exports-history" aria-labelledby="exports-history-title">
        <h2 id="exports-history-title">{copy.history}</h2>
        {exportsQuery.isPending ? (
          <p className="table-empty" role="status">{copy.loading}</p>
        ) : null}
        {exportsQuery.isError ? (
          <div className="form-message form-message--error" role="alert">
            <span>{loadError}</span>
            <button
              className="stage6-row-link"
              onClick={() => void exportsQuery.refetch()}
              type="button"
            >
              {copy.retryLoad}
            </button>
          </div>
        ) : null}
        {downloadError ? (
          <p className="form-message form-message--error" role="alert">
            {downloadError}
          </p>
        ) : null}
        {!exportsQuery.isPending && !exportsQuery.isError && exports.length === 0 ? (
          <div className="empty-state exports-empty-state">
            <div className="empty-state__icon"><Icon name="download" /></div>
            <h3>{copy.emptyTitle}</h3>
            <p>{copy.emptyBody}</p>
          </div>
        ) : null}
        <div className="export-list">
          {exports.map((item) => (
            <article className="export-card" key={item.id}>
              <header>
                <div>
                  <span
                    aria-live="polite"
                    className={`export-status export-status--${item.status}`}
                  >
                    {copy[item.status]}
                  </span>
                  <h3>{item.assignment_title}</h3>
                </div>
                <strong>{copy[item.export_type]}</strong>
              </header>
              <dl>
                <div><dt>{copy.batch}</dt><dd>{item.grading_job_id.slice(0, 8)}</dd></div>
                <div><dt>{copy.papers}</dt><dd>{item.paper_count}</dd></div>
                <div>
                  <dt>{copy.created}</dt>
                  <dd>{new Intl.DateTimeFormat(locale, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }).format(new Date(item.created_at))}</dd>
                </div>
              </dl>
              {item.status === "failed" ? (
                <p className="export-failure-reason">
                  {exportFailureLabel(item.error_code, language)}
                </p>
              ) : null}
              {item.status === "completed" && item.safe_filename ? (
                <button
                  aria-label={`${copy.download} ${item.safe_filename}`}
                  className="secondary-button export-download-button"
                  disabled={Boolean(downloadingId)}
                  onClick={() => void downloadExport(item.id)}
                  type="button"
                >
                  <Icon name="download" />
                  {downloadingId === item.id ? copy.downloading : copy.download}
                </button>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
