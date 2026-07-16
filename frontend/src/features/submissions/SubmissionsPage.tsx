import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import { Icon } from "../../app/icons";
import {
  useAppApi,
  type SubmissionState,
  type SubmissionView,
} from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";
import {
  validateSubmissionSelection,
  type SubmissionFileErrorCode,
  type SubmissionFileItem,
} from "./fileValidation";

type UploadState = SubmissionFileItem["state"] | "uploading" | "ready" | "duplicate" | "failed";

type UploadRow = Omit<SubmissionFileItem, "state" | "errorCode"> & {
  state: UploadState;
  errorCode: string | null;
};

const submissionsCopy = {
  zh: {
    title: "上传论文",
    intro: "上传 DOCX 或 PDF，系统将保存原文件并提取可定位的文本内容。",
    select: "选择 DOCX/PDF 文件",
    rules: "一次最多 100 篇，单篇不超过 20 MB；不支持扫描件、加密文件和旧版 .doc。",
    start: "开始上传",
    uploadingAll: "正在上传…",
    selectedFiles: "本次文件",
    savedFiles: "已保存论文",
    filename: "文件名",
    size: "大小",
    status: "状态",
    created: "上传时间",
    action: "操作",
    download: "下载原文件",
    back: "返回作业",
    rubric: "查看评分标准",
    emptySelection: "请选择要上传的论文。",
    emptySaved: "还没有已保存的论文。",
    loadFailed: "暂时无法加载论文列表。",
    assignmentFailed: "暂时无法加载作业。",
    notReady: "当前作业尚未确认评分标准，不能上传论文。",
    archived: "当前作业已归档，不能上传论文。",
    downloadFailed: "无法生成下载地址。",
    tooMany: "一次最多选择 100 篇论文。",
    selected: "待上传",
    rejected: "不可上传",
    uploading: "上传中",
    ready: "解析完成",
    duplicate: "重复文件",
    failed: "上传失败",
    uploaded: "等待解析",
    parsing: "解析中",
  },
  en: {
    title: "Upload papers",
    intro: "Upload DOCX or PDF files. The original and locatable extracted text are saved.",
    select: "Select DOCX/PDF files",
    rules: "Up to 100 files per selection and 20 MB per file. Scans, encrypted files, and .doc are not supported.",
    start: "Start upload",
    uploadingAll: "Uploading…",
    selectedFiles: "Current selection",
    savedFiles: "Saved papers",
    filename: "File",
    size: "Size",
    status: "Status",
    created: "Uploaded",
    action: "Action",
    download: "Download original",
    back: "Back to assignments",
    rubric: "View rubric",
    emptySelection: "Select papers to upload.",
    emptySaved: "No papers have been saved yet.",
    loadFailed: "Papers could not be loaded.",
    assignmentFailed: "The assignment could not be loaded.",
    notReady: "Confirm the rubric before uploading papers.",
    archived: "This assignment is archived and cannot accept uploads.",
    downloadFailed: "A download link could not be created.",
    tooMany: "Select no more than 100 papers at once.",
    selected: "Ready to upload",
    rejected: "Rejected",
    uploading: "Uploading",
    ready: "Parsed",
    duplicate: "Duplicate file",
    failed: "Upload failed",
    uploaded: "Waiting to parse",
    parsing: "Parsing",
  },
} as const;

const FILE_ERROR_COPY: Record<"zh" | "en", Record<SubmissionFileErrorCode, string>> = {
  zh: {
    file_empty: "文件内容为空。",
    file_too_large: "文件超过 20 MB。",
    extension_unsupported: "只支持 .docx 和 .pdf。",
  },
  en: {
    file_empty: "The file is empty.",
    file_too_large: "The file exceeds 20 MB.",
    extension_unsupported: "Only .docx and .pdf are supported.",
  },
};

const SERVER_ERROR_COPY: Record<"zh" | "en", Record<string, string>> = {
  zh: {
    document_encrypted: "加密文件无法解析。",
    pdf_scan_unsupported: "扫描版 PDF 暂不支持。",
    pdf_partial_scan_unsupported: "PDF 含无法提取文字的扫描页。",
    pdf_text_unextractable: "PDF 没有可提取的文字。",
    pdf_pages_too_many: "PDF 页数超过 200 页。",
    pdf_parse_failed: "PDF 已损坏或无法解析。",
    docx_macro_unsupported: "不支持含宏的 Word 文件。",
    docx_content_unsupported: "Word 文件含首版无法可靠提取的正文结构。",
    docx_archive_invalid: "Word 文件已损坏或压缩结构无效。",
    docx_archive_too_large: "Word 文件解压后的内容超过限制。",
    docx_xml_unsafe: "Word 文件包含不安全的 XML 内容。",
    docx_parse_failed: "Word 文件已损坏或无法解析。",
    document_empty: "文档没有可提取文字。",
    document_text_too_large: "文档可提取文字超过限制。",
    document_blocks_too_many: "文档可定位文本块超过限制。",
    media_type_unsupported: "只支持有效的 DOCX 或 PDF 文件。",
    extension_mismatch: "文件扩展名与真实格式不一致。",
    media_type_mismatch: "文件扩展名与真实格式不一致。",
    filename_invalid: "文件名无效。",
    storage_source_failed: "原文件存储失败。",
    storage_extracted_failed: "解析结果存储失败。",
    object_storage_unavailable: "对象存储暂时不可用。",
  },
  en: {
    document_encrypted: "Encrypted files cannot be parsed.",
    pdf_scan_unsupported: "Scanned PDFs are not supported.",
    pdf_partial_scan_unsupported: "The PDF contains scanned pages without extractable text.",
    pdf_text_unextractable: "The PDF has no extractable text.",
    pdf_pages_too_many: "The PDF exceeds 200 pages.",
    pdf_parse_failed: "The PDF is damaged or cannot be parsed.",
    docx_macro_unsupported: "Macro-enabled Word files are not supported.",
    docx_content_unsupported: "The Word file contains body content that cannot be extracted reliably.",
    docx_archive_invalid: "The Word file is damaged or has an invalid archive structure.",
    docx_archive_too_large: "The expanded Word document exceeds the limit.",
    docx_xml_unsafe: "The Word file contains unsafe XML content.",
    docx_parse_failed: "The Word file is damaged or cannot be parsed.",
    document_empty: "The document has no extractable text.",
    document_text_too_large: "The extractable text exceeds the limit.",
    document_blocks_too_many: "The document contains too many locatable text blocks.",
    media_type_unsupported: "Only valid DOCX or PDF files are supported.",
    extension_mismatch: "The extension does not match the actual file format.",
    media_type_mismatch: "The extension does not match the actual file format.",
    filename_invalid: "The file name is invalid.",
    storage_source_failed: "The original file could not be stored.",
    storage_extracted_failed: "The extracted result could not be stored.",
    object_storage_unavailable: "Object storage is temporarily unavailable.",
  },
};

function formatBytes(bytes: number, language: "zh" | "en") {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toLocaleString(language === "zh" ? "zh-CN" : "en", { maximumFractionDigits: 1 })} KB`;
  }
  return `${(bytes / (1024 * 1024)).toLocaleString(language === "zh" ? "zh-CN" : "en", { maximumFractionDigits: 1 })} MB`;
}

function savedStatusLabel(status: SubmissionState, language: "zh" | "en") {
  return submissionsCopy[language][status];
}

function uploadStatusLabel(row: UploadRow, language: "zh" | "en") {
  return submissionsCopy[language][row.state];
}

function errorLabel(row: UploadRow, language: "zh" | "en") {
  if (!row.errorCode) {
    return null;
  }
  if (row.errorCode in FILE_ERROR_COPY[language]) {
    return FILE_ERROR_COPY[language][row.errorCode as SubmissionFileErrorCode];
  }
  return SERVER_ERROR_COPY[language][row.errorCode] ?? submissionsCopy[language].failed;
}

function statusClass(status: UploadState | SubmissionState) {
  if (status === "ready" || status === "duplicate") {
    return "submission-status submission-status--success";
  }
  if (status === "rejected" || status === "failed") {
    return "submission-status submission-status--error";
  }
  return "submission-status";
}

function SavedSubmissionRow({
  submission,
  language,
  downloading,
  onDownload,
}: {
  submission: SubmissionView;
  language: "zh" | "en";
  downloading: boolean;
  onDownload: (submission: SubmissionView) => void;
}) {
  const copy = submissionsCopy[language];
  return (
    <tr>
      <td data-label={copy.filename}><strong>{submission.original_filename}</strong></td>
      <td data-label={copy.size}>{formatBytes(submission.file_size_bytes, language)}</td>
      <td data-label={copy.status}>
        <span className={statusClass(submission.status)}>{savedStatusLabel(submission.status, language)}</span>
        {submission.error_code ? <small className="submission-error">{SERVER_ERROR_COPY[language][submission.error_code] ?? submission.error_code}</small> : null}
      </td>
      <td data-label={copy.created}>
        {new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en", {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(new Date(submission.created_at))}
      </td>
      <td data-label={copy.action}>
        {submission.status === "ready" ? (
          <button className="stage6-row-link" disabled={downloading} onClick={() => onDownload(submission)} type="button">
            {copy.download}
          </button>
        ) : "—"}
      </td>
    </tr>
  );
}

export function SubmissionsPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { assignmentId = "" } = useParams();
  const { session } = useAuth();
  const api = useAppApi();
  const queryClient = useQueryClient();
  const copy = submissionsCopy[language];
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [selectionError, setSelectionError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [downloadingId, setDownloadingId] = useState("");
  const [downloadError, setDownloadError] = useState("");

  const assignmentQuery = useQuery({
    queryKey: ["assignment", assignmentId],
    enabled: Boolean(session && assignmentId),
    queryFn: () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.getAssignment(session, assignmentId);
    },
  });
  const submissionsQuery = useQuery({
    queryKey: ["submissions", assignmentId],
    enabled: Boolean(session && assignmentId),
    queryFn: () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.listSubmissions(session, assignmentId);
    },
  });
  const uploadableRows = useMemo(
    () => rows.filter((row) => row.state === "selected"),
    [rows],
  );
  const assignment = assignmentQuery.data;
  const canUpload = assignment?.status === "ready";

  function selectFiles(files: File[]) {
    const selection = validateSubmissionSelection(files);
    setSelectionError(selection.selectionError ? copy.tooMany : "");
    setRows(selection.items);
  }

  function updateRow(position: number, update: Partial<Pick<UploadRow, "state" | "errorCode">>) {
    setRows((current) => current.map((row) => (
      row.position === position ? { ...row, ...update } : row
    )));
  }

  async function uploadSelected() {
    if (!session || !canUpload || uploadableRows.length === 0 || isUploading) {
      return;
    }
    setIsUploading(true);
    const uploadSession = session;
    const queue = [...uploadableRows];
    let cursor = 0;
    async function worker() {
      while (cursor < queue.length) {
        const row = queue[cursor];
        cursor += 1;
        updateRow(row.position, { state: "uploading", errorCode: null });
        try {
          const result = await api.uploadSubmission(uploadSession, assignmentId, row.file);
          updateRow(row.position, {
            state: result.duplicate ? "duplicate" : "ready",
            errorCode: null,
          });
        } catch (error) {
          updateRow(row.position, {
            state: "failed",
            errorCode: error instanceof ApiRequestError ? (error.code ?? "upload_failed") : "upload_failed",
          });
        }
      }
    }
    try {
      await Promise.all(Array.from({ length: Math.min(3, queue.length) }, worker));
      await queryClient.invalidateQueries({ queryKey: ["submissions", assignmentId] });
    } finally {
      setIsUploading(false);
    }
  }

  async function downloadSubmission(submission: SubmissionView) {
    if (!session || downloadingId) {
      return;
    }
    setDownloadingId(submission.id);
    setDownloadError("");
    try {
      const result = await api.createSubmissionDownload(session, assignmentId, submission.id);
      const link = document.createElement("a");
      link.href = result.url;
      link.rel = "noopener noreferrer";
      link.click();
    } catch {
      setDownloadError(copy.downloadFailed);
    } finally {
      setDownloadingId("");
    }
  }

  if (assignmentQuery.isPending) {
    return <div className="page stage6-page"><p className="table-empty">{copy.assignmentFailed}</p></div>;
  }
  if (assignmentQuery.isError || !assignment) {
    return <div className="page stage6-page"><p className="form-message form-message--error" role="alert">{copy.assignmentFailed}</p></div>;
  }

  return (
    <div className="page stage6-page submissions-page">
      <header className="stage6-page-header">
        <div><h1>{copy.title}</h1><p>{assignment.title}</p></div>
        <Link className="secondary-button" to={`/assignments/${assignmentId}/rubric`}>{copy.rubric}</Link>
      </header>

      {assignment.status === "draft" ? <p className="form-message form-message--error" role="alert">{copy.notReady}</p> : null}
      {assignment.status === "archived" ? <p className="form-message form-message--error" role="alert">{copy.archived}</p> : null}

      <section className="submission-picker" aria-labelledby="submission-picker-title">
        <div>
          <h2 id="submission-picker-title">{copy.intro}</h2>
          <p>{copy.rules}</p>
        </div>
        <label className={canUpload && !isUploading ? "secondary-button submission-file-button" : "secondary-button submission-file-button submission-file-button--disabled"}>
          <Icon name="document" />
          <span>{copy.select}</span>
          <input
            accept=".docx,.pdf"
            aria-label={copy.select}
            disabled={!canUpload || isUploading}
            multiple
            onChange={(event) => {
              selectFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
            type="file"
          />
        </label>
      </section>

      {selectionError ? <p className="form-message form-message--error" role="alert">{selectionError}</p> : null}
      {rows.length > 0 ? (
        <section className="submission-batch" aria-labelledby="submission-batch-title">
          <div className="submission-section-heading">
            <h2 id="submission-batch-title">{copy.selectedFiles}</h2>
            <button className="primary-button" disabled={!canUpload || uploadableRows.length === 0 || isUploading} onClick={() => void uploadSelected()} type="button">
              {isUploading ? copy.uploadingAll : copy.start}
            </button>
          </div>
          <div className="account-table-wrap stage6-table-wrap">
            <table className="account-table stage6-table">
              <thead><tr><th>{copy.filename}</th><th>{copy.size}</th><th>{copy.status}</th></tr></thead>
              <tbody>{rows.map((row) => (
                <tr key={`${row.position}-${row.file.name}-${row.file.lastModified}`}>
                  <td data-label={copy.filename}><strong>{row.file.name}</strong></td>
                  <td data-label={copy.size}>{formatBytes(row.file.size, language)}</td>
                  <td data-label={copy.status}>
                    <span className={statusClass(row.state)}>{uploadStatusLabel(row, language)}</span>
                    {errorLabel(row, language) ? <small className="submission-error">{errorLabel(row, language)}</small> : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
      ) : null}

      <section className="submission-saved" aria-labelledby="submission-saved-title">
        <div className="submission-section-heading"><h2 id="submission-saved-title">{copy.savedFiles}</h2></div>
        {submissionsQuery.isPending ? <p className="table-empty">{copy.emptySaved}</p> : null}
        {submissionsQuery.isError ? <p className="form-message form-message--error" role="alert">{copy.loadFailed}</p> : null}
        {downloadError ? <p className="form-message form-message--error" role="alert">{downloadError}</p> : null}
        {!submissionsQuery.isPending && !submissionsQuery.isError && submissionsQuery.data?.length === 0 ? <p className="table-empty">{copy.emptySaved}</p> : null}
        {submissionsQuery.data && submissionsQuery.data.length > 0 ? (
          <div className="account-table-wrap stage6-table-wrap">
            <table className="account-table stage6-table">
              <thead><tr><th>{copy.filename}</th><th>{copy.size}</th><th>{copy.status}</th><th>{copy.created}</th><th>{copy.action}</th></tr></thead>
              <tbody>{submissionsQuery.data.map((submission) => (
                <SavedSubmissionRow downloading={downloadingId === submission.id} key={submission.id} language={language} onDownload={(item) => void downloadSubmission(item)} submission={submission} />
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </section>

      <footer className="submission-footer"><Link className="secondary-button" to="/assignments">{copy.back}</Link></footer>
    </div>
  );
}
