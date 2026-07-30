import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Fragment,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import { Icon } from "../../app/icons";
import {
  useAppApi,
  type DocumentBlock,
  type ReviewDetail,
  type ReviewDraftInput,
  type ReviewEvidence,
} from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";
import { calculateReviewTotal } from "./decimal";
import { reviewCopy } from "./reviewCopy";

type Panel = "queue" | "paper" | "review";

function attemptEvidence(detail: ReviewDetail): ReviewEvidence[] {
  return [
    ...detail.attempt.dimensions.flatMap((dimension) =>
      dimension.evidence.map((evidence) => ({
        ...evidence,
        target_type: "dimension" as const,
        target_id: dimension.dimension_id,
      })),
    ),
    ...detail.attempt.deductions.flatMap((deduction) =>
      deduction.evidence.map((evidence) => ({
        ...evidence,
        target_type: "deduction" as const,
        target_id: deduction.deduction_id,
      })),
    ),
  ];
}

function initialForm(detail: ReviewDetail): ReviewDraftInput {
  if (detail.draft) {
    return {
      attempt_id: detail.draft.attempt_id,
      criteria: detail.draft.criteria,
      deductions: detail.draft.deductions,
      evidence: detail.draft.evidence,
      overall_feedback: detail.draft.overall_feedback,
      change_reason: detail.draft.change_reason,
    };
  }
  return {
    attempt_id: detail.attempt.id,
    criteria: detail.attempt.dimensions.map((criterion) => ({
      dimension_id: criterion.dimension_id,
      score: criterion.score,
      reason: criterion.reason,
      revision_suggestions: criterion.revision_suggestions,
    })),
    deductions: detail.attempt.deductions.map((deduction) => ({
      deduction_id: deduction.deduction_id,
      applied: deduction.applied,
      reason: deduction.reason,
    })),
    evidence: attemptEvidence(detail),
    overall_feedback: detail.attempt.overall_feedback,
    change_reason: null,
  };
}

function HighlightedBlock({ block, evidence }: { block: DocumentBlock; evidence: string[] }) {
  const ranges = evidence
    .map((quote) => ({ quote, start: block.text.indexOf(quote) }))
    .filter(({ start }) => start >= 0)
    .sort((left, right) => left.start - right.start);
  const parts: Array<{ text: string; highlighted: boolean }> = [];
  let cursor = 0;
  for (const range of ranges) {
    if (range.start < cursor) continue;
    if (range.start > cursor) {
      parts.push({ text: block.text.slice(cursor, range.start), highlighted: false });
    }
    parts.push({ text: range.quote, highlighted: true });
    cursor = range.start + range.quote.length;
  }
  if (cursor < block.text.length) {
    parts.push({ text: block.text.slice(cursor), highlighted: false });
  }
  return (
    <>
      {parts.map((part, index) =>
        part.highlighted ? (
          <mark key={`${index}-${part.text}`}>{part.text}</mark>
        ) : (
          <Fragment key={`${index}-${part.text}`}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

export function ReviewWorkbenchPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { jobId = "", itemId = "" } = useParams();
  const { session } = useAuth();
  const api = useAppApi();
  const queryClient = useQueryClient();
  const copy = reviewCopy[language];
  const [activePanel, setActivePanel] = useState<Panel>("paper");
  const [form, setForm] = useState<ReviewDraftInput | null>(null);
  const [target, setTarget] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [regradedItemId, setRegradedItemId] = useState<string | null>(null);
  const tabRefs = useRef<Record<Panel, HTMLButtonElement | null>>({
    queue: null,
    paper: null,
    review: null,
  });
  const detailQuery = useQuery({
    queryKey: ["review", jobId, itemId],
    enabled: Boolean(session && jobId && itemId),
    queryFn: async () => {
      if (!session) throw new Error("登录会话不存在");
      const detail = await api.getReview(session, jobId, itemId);
      setForm(initialForm(detail));
      setTarget(`dimension:${detail.rubric.dimensions[0]?.id ?? ""}`);
      return detail;
    },
  });
  const jobsQuery = useQuery({
    queryKey: ["review-jobs"],
    enabled: Boolean(session),
    queryFn: () => {
      if (!session) throw new Error("登录会话不存在");
      return api.listReviewJobs(session);
    },
  });
  const detail = detailQuery.data;
  const currentJob = jobsQuery.data?.find((job) => job.id === jobId);
  const isConfirmed = detail?.item_status === "completed" || detail?.draft?.status === "confirmed";
  const regradeSubmitted = regradedItemId === itemId;
  const preview = useMemo(() => {
    if (!detail || !form) return null;
    return calculateReviewTotal(
      form.criteria.map((criterion) => criterion.score),
      form.deductions.map((deduction) => ({
        applied: deduction.applied,
        points:
          detail.rubric.deductions.find((item) => item.id === deduction.deduction_id)
            ?.points ?? "0",
      })),
    );
  }, [detail, form]);

  function actionError(actionError: unknown) {
    setMessage("");
    setError(
      actionError instanceof ApiRequestError && actionError.status === 409
        ? copy.conflict
        : copy.actionFailed,
    );
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!session || !form) throw new Error("复核表单尚未加载");
      return api.saveReviewDraft(session, jobId, itemId, form);
    },
    onSuccess: async () => {
      setError("");
      setMessage(copy.saved);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review", jobId, itemId] }),
        queryClient.invalidateQueries({ queryKey: ["review-jobs"] }),
      ]);
    },
    onError: actionError,
  });
  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!session || !form) throw new Error("复核表单尚未加载");
      return api.confirmReview(session, jobId, itemId, form);
    },
    onSuccess: async () => {
      setError("");
      setMessage(copy.confirmed);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["review", jobId, itemId] }),
        queryClient.invalidateQueries({ queryKey: ["review-jobs"] }),
      ]);
    },
    onError: actionError,
  });
  const regradeMutation = useMutation({
    mutationFn: async (regradeItemId: string) => {
      if (!session) throw new Error("登录会话不存在");
      await api.regradeReview(session, jobId, regradeItemId);
    },
    onSuccess: async (_result, regradeItemId) => {
      setError("");
      setMessage(copy.regradeSubmitted);
      setRegradedItemId(regradeItemId);
      await queryClient.invalidateQueries({ queryKey: ["review-jobs"] });
    },
    onError: actionError,
  });
  const reviewActionPending =
    saveMutation.isPending || confirmMutation.isPending || regradeMutation.isPending;

  function updateCriterion(
    dimensionId: string,
    field: "score" | "reason" | "revision_suggestions",
    value: string,
  ) {
    setForm((current) =>
      current
        ? {
            ...current,
            criteria: current.criteria.map((criterion) =>
              criterion.dimension_id === dimensionId
                ? {
                    ...criterion,
                    [field]:
                      field === "revision_suggestions"
                        ? value.split("\n").filter((line) => line.length > 0)
                        : value,
                  }
                : criterion,
            ),
          }
        : current,
    );
  }

  function addEvidence() {
    if (!form || !target) {
      setError(copy.selectTarget);
      return;
    }
    const selection = window.getSelection();
    if (!selection || selection.rangeCount !== 1 || !selection.toString().trim()) {
      setError(copy.selectionEmpty);
      return;
    }
    const range = selection.getRangeAt(0);
    const startElement =
      range.startContainer instanceof Element
        ? range.startContainer
        : range.startContainer.parentElement;
    const endElement =
      range.endContainer instanceof Element ? range.endContainer : range.endContainer.parentElement;
    const startBlock = startElement?.closest<HTMLElement>("[data-block-id]");
    const endBlock = endElement?.closest<HTMLElement>("[data-block-id]");
    if (!startBlock || !endBlock) {
      setError(copy.selectionEmpty);
      return;
    }
    if (startBlock.dataset.blockId !== endBlock.dataset.blockId) {
      setError(copy.selectionCrossBlock);
      return;
    }
    const quote = selection.toString();
    const source = detail?.document.blocks.find(
      (block) => block.block_id === startBlock.dataset.blockId,
    );
    if (!source || !source.text.includes(quote)) {
      setError(copy.selectionEmpty);
      return;
    }
    const [target_type, target_id] = target.split(":") as [
      "dimension" | "deduction",
      string,
    ];
    setForm({
      ...form,
      evidence: [
        ...form.evidence,
        { target_type, target_id, block_id: source.block_id, quote },
      ],
    });
    selection.removeAllRanges();
    setError("");
  }

  function focusEvidence(evidence: ReviewEvidence) {
    setActivePanel("paper");
    window.setTimeout(() => {
      const block = document.querySelector<HTMLElement>(
        `[data-block-id="${evidence.block_id}"]`,
      );
      block?.scrollIntoView({ behavior: "smooth", block: "center" });
      block?.focus({ preventScroll: true });
    });
  }

  function moveTab(event: KeyboardEvent<HTMLButtonElement>, current: Panel) {
    if (!(["ArrowLeft", "ArrowRight"] as const).includes(event.key as "ArrowLeft")) return;
    event.preventDefault();
    const panels: Panel[] = ["queue", "paper", "review"];
    const change = event.key === "ArrowRight" ? 1 : -1;
    const next = panels[(panels.indexOf(current) + change + panels.length) % panels.length];
    setActivePanel(next);
    tabRefs.current[next]?.focus();
  }

  if (detailQuery.isPending) {
    return <div className="page review-workbench-loading">{copy.reviewLoading}</div>;
  }
  if (detailQuery.isError || !detail) {
    return (
      <div className="page">
        <p className="form-message form-message--error" role="alert">
          {copy.reviewLoadFailed}
        </p>
      </div>
    );
  }
  if (!form) {
    return <div className="page review-workbench-loading">{copy.reviewLoading}</div>;
  }

  const evidenceByBlock = new Map<string, string[]>();
  for (const evidence of form.evidence) {
    const quotes = evidenceByBlock.get(evidence.block_id) ?? [];
    quotes.push(evidence.quote);
    evidenceByBlock.set(evidence.block_id, quotes);
  }

  return (
    <div className="review-workbench-page">
      <header className="review-workbench-header">
        <div>
          <Link className="stage6-row-link" to="/grading-jobs">
            <Icon name="chevronLeft" /> {copy.back}
          </Link>
          <h1>{detail.original_filename}</h1>
          <p>{detail.assignment_title} · {detail.attempt.model}</p>
        </div>
        <div className="review-score-summary" aria-live="polite">
          <span>{copy.finalScore}</span>
          <strong>{preview?.finalScore ?? "—"} / {detail.rubric.total_score}</strong>
        </div>
      </header>

      <div className="review-mobile-tabs" role="tablist" aria-label={copy.review}>
        {(["queue", "paper", "review"] as const).map((panel) => (
          <button
            aria-controls={`review-panel-${panel}`}
            aria-selected={activePanel === panel}
            id={`review-tab-${panel}`}
            key={panel}
            onClick={() => setActivePanel(panel)}
            onKeyDown={(event) => moveTab(event, panel)}
            ref={(node) => {
              tabRefs.current[panel] = node;
            }}
            role="tab"
            tabIndex={activePanel === panel ? 0 : -1}
            type="button"
          >
            {copy[panel]}
          </button>
        ))}
      </div>

      {message ? <p className="review-floating-message form-message--success">{message}</p> : null}
      {error ? (
        <p className="review-floating-message form-message--error" role="alert">
          {error}
        </p>
      ) : null}
      {isConfirmed ? <p className="review-confirmed-banner">{copy.confirmed}</p> : null}

      <div className="review-workbench">
        <aside
          aria-labelledby="review-tab-queue"
          className="review-panel review-queue-panel"
          data-mobile-active={activePanel === "queue"}
          id="review-panel-queue"
          role="tabpanel"
        >
          <h2>{copy.queue}</h2>
          <ol>
            {currentJob?.items.map((item) => (
              <li className={item.id === itemId ? "is-current" : ""} key={item.id}>
                {item.review_available &&
                (item.status === "needs_review" || item.status === "completed") ? (
                  <Link to={`/grading-jobs/${jobId}/reviews/${item.id}`}>
                    <strong>{item.original_filename}</strong>
                    <span>{item.status === "completed" ? copy.completed : copy.needsReview}</span>
                  </Link>
                ) : (
                  <div>
                    <strong>{item.original_filename}</strong>
                    <span>{copy.unavailable}</span>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </aside>

        <main
          aria-labelledby="review-tab-paper"
          className="review-panel review-paper-panel"
          data-mobile-active={activePanel === "paper"}
          id="review-panel-paper"
          role="tabpanel"
        >
          <div className="review-panel-heading">
            <div>
              <h2>{copy.paper}</h2>
              <p>{detail.assignment_instructions}</p>
            </div>
            <div className="review-evidence-adder">
              <label>
                <span>{copy.evidenceTarget}</span>
                <select
                  disabled={isConfirmed}
                  onChange={(event) => setTarget(event.target.value)}
                  value={target}
                >
                  {detail.rubric.dimensions.map((dimension) => (
                    <option key={dimension.id} value={`dimension:${dimension.id}`}>
                      {dimension.name}
                    </option>
                  ))}
                  {detail.rubric.deductions.map((deduction) => (
                    <option key={deduction.id} value={`deduction:${deduction.id}`}>
                      {deduction.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="secondary-button"
                disabled={isConfirmed}
                onClick={addEvidence}
                type="button"
              >
                {copy.addEvidence}
              </button>
            </div>
          </div>
          <article className="review-document" lang="en">
            {detail.document.blocks.map((block) => (
              <section
                className="review-document-block"
                data-block-id={block.block_id}
                key={block.block_id}
                tabIndex={-1}
              >
                <small>{copy.block} {block.block_id}</small>
                <p>
                  <HighlightedBlock
                    block={block}
                    evidence={evidenceByBlock.get(block.block_id) ?? []}
                  />
                </p>
              </section>
            ))}
          </article>
        </main>

        <aside
          aria-labelledby="review-tab-review"
          className="review-panel review-form-panel"
          data-mobile-active={activePanel === "review"}
          id="review-panel-review"
          role="tabpanel"
        >
          <h2>{copy.rubric}</h2>
          <fieldset disabled={isConfirmed || regradeSubmitted}>
            {detail.rubric.dimensions.map((dimension) => {
              const criterion = form.criteria.find(
                (item) => item.dimension_id === dimension.id,
              );
              if (!criterion) return null;
              return (
                <section className="review-rubric-card" key={dimension.id}>
                  <header>
                    <h3>{dimension.name}</h3>
                    <span>/ {dimension.max_score}</span>
                  </header>
                  <p>{dimension.description}</p>
                  <label>
                    <span>{copy.score}</span>
                    <input
                      inputMode="decimal"
                      max={dimension.max_score}
                      min="0"
                      onChange={(event) =>
                        updateCriterion(dimension.id, "score", event.target.value)
                      }
                      step={detail.rubric.score_step}
                      type="text"
                      value={criterion.score}
                    />
                  </label>
                  <label>
                    <span>{copy.reason}</span>
                    <textarea
                      lang="en"
                      onChange={(event) =>
                        updateCriterion(dimension.id, "reason", event.target.value)
                      }
                      value={criterion.reason}
                    />
                  </label>
                  <label>
                    <span>{copy.suggestions}</span>
                    <textarea
                      lang="en"
                      onChange={(event) =>
                        updateCriterion(
                          dimension.id,
                          "revision_suggestions",
                          event.target.value,
                        )
                      }
                      value={criterion.revision_suggestions.join("\n")}
                    />
                  </label>
                </section>
              );
            })}

            <section className="review-rubric-card">
              <h3>{copy.deductions}</h3>
              {detail.rubric.deductions.length === 0 ? <p>{copy.noDeductions}</p> : null}
              {detail.rubric.deductions.map((deduction) => {
                const value = form.deductions.find(
                  (item) => item.deduction_id === deduction.id,
                );
                if (!value) return null;
                return (
                  <div className="review-deduction" key={deduction.id}>
                    <label className="review-checkbox-label">
                      <input
                        checked={value.applied}
                        onChange={(event) =>
                          setForm({
                            ...form,
                            deductions: form.deductions.map((item) =>
                              item.deduction_id === deduction.id
                                ? { ...item, applied: event.target.checked }
                                : item,
                            ),
                          })
                        }
                        type="checkbox"
                      />
                      <span>{copy.applied}: {deduction.name} (−{deduction.points})</span>
                    </label>
                    <textarea
                      aria-label={`${deduction.name} ${copy.reason}`}
                      lang="en"
                      onChange={(event) =>
                        setForm({
                          ...form,
                          deductions: form.deductions.map((item) =>
                            item.deduction_id === deduction.id
                              ? { ...item, reason: event.target.value }
                              : item,
                          ),
                        })
                      }
                      value={value.reason}
                    />
                  </div>
                );
              })}
            </section>

            <section className="review-rubric-card">
              <h3>{copy.evidence}</h3>
              <ul className="review-evidence-list">
                {form.evidence.map((evidence, index) => (
                  <li key={`${evidence.target_type}-${evidence.target_id}-${index}`}>
                    <button onClick={() => focusEvidence(evidence)} type="button">
                      <strong>{evidence.target_id}</strong>
                      <span>{evidence.block_id}: “{evidence.quote}”</span>
                    </button>
                    <button
                      aria-label={`${copy.removeEvidence} ${evidence.quote}`}
                      className="review-evidence-remove"
                      onClick={() =>
                        setForm({
                          ...form,
                          evidence: form.evidence.filter((_item, itemIndex) => itemIndex !== index),
                        })
                      }
                      type="button"
                    >
                      <Icon name="close" />
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <label className="review-full-field">
              <span>{copy.feedback}</span>
              <textarea
                lang="en"
                onChange={(event) =>
                  setForm({ ...form, overall_feedback: event.target.value })
                }
                value={form.overall_feedback}
              />
            </label>
            <label className="review-full-field">
              <span>{copy.changeReason}</span>
              <textarea
                onChange={(event) =>
                  setForm({ ...form, change_reason: event.target.value || null })
                }
                value={form.change_reason ?? ""}
              />
              <small>{copy.changeReasonHint}</small>
            </label>
          </fieldset>

          <section className="review-total-card">
            <div><span>{copy.subtotal}</span><strong>{preview?.subtotal ?? "—"}</strong></div>
            <div><span>{copy.deductionTotal}</span><strong>−{preview?.deductionTotal ?? "—"}</strong></div>
            <div className="review-total-card__final">
              <span>{copy.finalScore}</span>
              <strong>{preview?.finalScore ?? "—"} / {detail.rubric.total_score}</strong>
            </div>
            <small>{copy.exactServer}</small>
          </section>

          <div className="review-actions">
            <button
              className="secondary-button"
              disabled={isConfirmed || regradeSubmitted || reviewActionPending}
              onClick={() => saveMutation.mutate()}
              type="button"
            >
              {saveMutation.isPending ? copy.saving : copy.save}
            </button>
            <button
              className="secondary-button"
              disabled={isConfirmed || regradeSubmitted || reviewActionPending}
              onClick={() => {
                if (window.confirm(copy.regradePrompt)) regradeMutation.mutate(itemId);
              }}
              type="button"
            >
              {regradeMutation.isPending ? copy.regrading : copy.regrade}
            </button>
            <button
              className="primary-button"
              disabled={isConfirmed || regradeSubmitted || reviewActionPending}
              onClick={() => {
                if (window.confirm(copy.confirmPrompt)) confirmMutation.mutate();
              }}
              type="button"
            >
              {confirmMutation.isPending ? copy.confirming : copy.confirm}
            </button>
            <small>{copy.confirmWarning}</small>
          </div>
        </aside>
      </div>
    </div>
  );
}
