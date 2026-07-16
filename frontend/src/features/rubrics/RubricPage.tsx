import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import {
  useAppApi,
  type RubricDimension,
  type RubricDraftInput,
  type RubricView,
  type StructuredRubric,
} from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";

const rubricCopy = {
  zh: {
    title: "设置评分标准",
    versions: "版本记录",
    original: "原始评分标准",
    model: "结构化模型",
    selectProvider: "请选择已启用的供应商",
    defaultModel: "管理员默认模型",
    savedProvider: "已保存供应商",
    savedModel: "生成模型",
    generate: "生成结构化草稿",
    regenerate: "重新生成",
    generating: "正在生成…",
    total: "总分",
    step: "评分步长",
    draft: "草稿",
    confirmed: "已确认",
    superseded: "已替代",
    band: "分档",
    minScore: "最低分",
    maxScore: "最高分",
    description: "描述",
    scoreUnit: "分",
    evidence: "证据要求",
    deductions: "统一扣分项",
    confirm: "确认评分标准",
    confirming: "正在确认…",
    frozen: "当前版本已确认并冻结。",
    freezeNotice: "确认后当前版本将冻结；后续修改会创建新版本。",
    back: "返回作业",
    loading: "正在加载评分标准…",
    failed: "暂时无法加载评分标准。",
    providerEmpty: "管理员尚未启用可用的模型供应商。",
    actionFailed: "操作失败，请重试。",
    createRevision: "创建新版本",
    upload: "上传论文",
    revisionTitle: "创建评分标准新版本",
    revisionRubric: "新版原始评分标准",
    saveRevision: "保存新版本",
    savingRevision: "正在保存…",
    cancelRevision: "取消",
  },
  en: {
    title: "Set rubric",
    versions: "Versions",
    original: "Original rubric",
    model: "Structuring model",
    selectProvider: "Select an enabled provider",
    defaultModel: "Administrator default model",
    savedProvider: "Saved provider",
    savedModel: "Generation model",
    generate: "Generate structured draft",
    regenerate: "Regenerate",
    generating: "Generating…",
    total: "Total",
    step: "Score step",
    draft: "Draft",
    confirmed: "Confirmed",
    superseded: "Superseded",
    band: "Band",
    minScore: "Minimum",
    maxScore: "Maximum",
    description: "Description",
    scoreUnit: "points",
    evidence: "Evidence requirements",
    deductions: "Deductions",
    confirm: "Confirm rubric",
    confirming: "Confirming…",
    frozen: "The current version is confirmed and frozen.",
    freezeNotice: "Confirmation freezes this version; later edits create a new version.",
    back: "Back to assignments",
    loading: "Loading rubric…",
    failed: "The rubric could not be loaded.",
    providerEmpty: "No model provider has been enabled by the administrator.",
    actionFailed: "The action failed. Please try again.",
    createRevision: "Create new version",
    upload: "Upload papers",
    revisionTitle: "Create a new rubric version",
    revisionRubric: "New original rubric",
    saveRevision: "Save new version",
    savingRevision: "Saving…",
    cancelRevision: "Cancel",
  },
} as const;

function RubricDimensionView({
  dimension,
  evidenceLabel,
  labels,
}: {
  dimension: RubricDimension;
  evidenceLabel: string;
  labels: {
    band: string;
    minScore: string;
    maxScore: string;
    description: string;
    scoreUnit: string;
  };
}) {
  return (
    <section className="rubric-dimension">
      <header>
        <h2>{dimension.name}</h2>
        <strong>{dimension.max_score} {labels.scoreUnit}</strong>
      </header>
      <p>{dimension.description}</p>
      <div className="rubric-dimension__content">
        <table className="rubric-bands">
          <thead><tr><th>{labels.band}</th><th>{labels.minScore}</th><th>{labels.maxScore}</th><th>{labels.description}</th></tr></thead>
          <tbody>
            {dimension.bands.map((band) => (
              <tr key={`${band.min_score}-${band.max_score}`}>
                <td>{band.label}</td><td>{band.min_score}</td><td>{band.max_score}</td><td>{band.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <section className="rubric-evidence">
          <h3>{evidenceLabel}</h3>
          <ul>{dimension.evidence_requirements.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      </div>
    </section>
  );
}

function StructuredRubricView({
  rubric,
  evidenceLabel,
  deductionsLabel,
  labels,
}: {
  rubric: StructuredRubric;
  evidenceLabel: string;
  deductionsLabel: string;
  labels: {
    band: string;
    minScore: string;
    maxScore: string;
    description: string;
    scoreUnit: string;
  };
}) {
  return (
    <div className="structured-rubric">
      {rubric.dimensions.map((dimension) => (
        <RubricDimensionView dimension={dimension} evidenceLabel={evidenceLabel} key={dimension.id} labels={labels} />
      ))}
      <section className="rubric-deductions">
        <h2>{deductionsLabel}</h2>
        {rubric.deductions.length === 0 ? <p>—</p> : (
          <table className="rubric-bands">
            <tbody>{rubric.deductions.map((deduction) => (
              <tr key={deduction.id}><td><strong>{deduction.name}</strong></td><td>-{deduction.points} {labels.scoreUnit}</td><td>{deduction.description}</td></tr>
            ))}</tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function currentRubric(rubrics: RubricView[]) {
  return rubrics.find((item) => item.status === "draft")
    ?? rubrics.find((item) => item.status === "confirmed")
    ?? rubrics[0];
}

export function RubricPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { assignmentId = "" } = useParams();
  const { session } = useAuth();
  const api = useAppApi();
  const queryClient = useQueryClient();
  const copy = rubricCopy[language];
  const [providerId, setProviderId] = useState("");
  const [error, setError] = useState("");
  const [showRevision, setShowRevision] = useState(false);
  const [revision, setRevision] = useState<RubricDraftInput>({
    originalRubric: "",
    totalScore: "",
    scoreStep: "",
  });
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
  const providersQuery = useQuery({
    queryKey: ["teacher-providers"],
    enabled: Boolean(session),
    queryFn: () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.listTeacherProviders(session);
    },
  });
  const rubric = assignmentQuery.data ? currentRubric(assignmentQuery.data.rubric_versions) : undefined;
  const effectiveProviderId = providerId || rubric?.provider_config_id || "";
  const selectedProvider = providersQuery.data?.find((provider) => provider.provider_id === effectiveProviderId);
  const savedProviderUnavailable = Boolean(
    rubric?.provider_config_id
    && !providersQuery.isPending
    && !selectedProvider,
  );

  async function refreshAssignment() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["assignment", assignmentId] }),
      queryClient.invalidateQueries({ queryKey: ["assignments"] }),
    ]);
  }

  const structureMutation = useMutation({
    mutationFn: async () => {
      if (!session || !rubric || !effectiveProviderId) {
        throw new Error("缺少生成参数");
      }
      return api.structureRubric(session, assignmentId, rubric.id, effectiveProviderId);
    },
    onSuccess: refreshAssignment,
    onError: (mutationError) => setError(mutationError instanceof ApiRequestError ? mutationError.message : copy.actionFailed),
  });
  const confirmMutation = useMutation({
    mutationFn: async () => {
      if (!session || !rubric) {
        throw new Error("缺少确认参数");
      }
      return api.confirmRubric(session, assignmentId, rubric.id);
    },
    onSuccess: refreshAssignment,
    onError: (mutationError) => setError(mutationError instanceof ApiRequestError ? mutationError.message : copy.actionFailed),
  });
  const revisionMutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.createRubricDraft(session, assignmentId, revision);
    },
    onSuccess: async () => {
      setShowRevision(false);
      setProviderId("");
      await refreshAssignment();
    },
    onError: (mutationError) => setError(mutationError instanceof ApiRequestError ? mutationError.message : copy.actionFailed),
  });

  if (assignmentQuery.isPending) {
    return <div className="page stage6-page"><p className="table-empty">{copy.loading}</p></div>;
  }
  if (assignmentQuery.isError || !assignmentQuery.data || !rubric) {
    return <div className="page stage6-page"><p className="form-message form-message--error" role="alert">{copy.failed}</p></div>;
  }
  const assignment = assignmentQuery.data;
  const isConfirmed = rubric.status === "confirmed";

  return (
    <div className="page stage6-page rubric-page">
      <header className="rubric-page-header">
        <div><h1>{copy.title}</h1><p>{assignment.title}</p></div>
        <div className="rubric-score-summary"><span>{copy.total} <strong>{rubric.total_score}</strong></span><span>{copy.step} <strong>{rubric.score_step}</strong></span></div>
      </header>
      <div className="rubric-workspace">
        <aside className="rubric-sidebar">
          <section><h2>{copy.versions}</h2>{assignment.rubric_versions.map((version) => <p className={version.id === rubric.id ? "rubric-version rubric-version--active" : "rubric-version"} key={version.id}>v{version.version} {version.status === "draft" ? copy.draft : version.status === "confirmed" ? copy.confirmed : copy.superseded}</p>)}</section>
          <section><h2>{copy.original}</h2><p>{rubric.original_rubric}</p></section>
          <section className="rubric-provider-picker">
            <label htmlFor="rubric-provider">{copy.model}</label>
            <select disabled={isConfirmed || providersQuery.isPending} id="rubric-provider" value={effectiveProviderId} onChange={(event) => setProviderId(event.target.value)}>
              <option value="">{copy.selectProvider}</option>
              {savedProviderUnavailable && rubric.provider_config_id ? <option value={rubric.provider_config_id}>{copy.savedProvider} · {rubric.model ?? "—"}</option> : null}
              {providersQuery.data?.map((provider) => <option key={provider.provider_id} value={provider.provider_id}>{provider.provider_name} · {provider.default_model}</option>)}
            </select>
            {selectedProvider ? <p>{copy.defaultModel}：{selectedProvider.default_model}</p> : null}
            {!selectedProvider && rubric.model ? <p>{copy.savedModel}：{rubric.model}</p> : null}
            {!providersQuery.isPending && providersQuery.data?.length === 0 ? <p className="form-message form-message--error">{copy.providerEmpty}</p> : null}
            {!isConfirmed ? <button className="secondary-button" disabled={!effectiveProviderId || !selectedProvider || structureMutation.isPending} onClick={() => { setError(""); structureMutation.mutate(); }} type="button">{structureMutation.isPending ? copy.generating : rubric.structured_rubric ? copy.regenerate : copy.generate}</button> : null}
          </section>
        </aside>
        <main className="rubric-main">
          {isConfirmed ? <p className="rubric-frozen" role="status">{copy.frozen}</p> : null}
          {error ? <p className="form-message form-message--error" role="alert">{error}</p> : null}
          {rubric.structured_rubric ? <StructuredRubricView rubric={rubric.structured_rubric} evidenceLabel={copy.evidence} deductionsLabel={copy.deductions} labels={{ band: copy.band, minScore: copy.minScore, maxScore: copy.maxScore, description: copy.description, scoreUnit: copy.scoreUnit }} /> : <p className="rubric-empty">{copy.generate}</p>}
        </main>
      </div>
      <footer className="rubric-actions">
        <p>{copy.freezeNotice}</p>
        <div>
          <Link className="secondary-button" to="/assignments">{copy.back}</Link>
          {assignment.status === "ready" ? <Link className="primary-button" to={`/assignments/${assignmentId}/submissions`}>{copy.upload}</Link> : null}
          {isConfirmed ? <button className="primary-button" onClick={() => { setRevision({ originalRubric: rubric.original_rubric, totalScore: rubric.total_score, scoreStep: rubric.score_step }); setShowRevision(true); setError(""); }} type="button">{copy.createRevision}</button> : null}
          {!isConfirmed && rubric.structured_rubric ? <button className="primary-button" disabled={confirmMutation.isPending} onClick={() => { setError(""); confirmMutation.mutate(); }} type="button">{confirmMutation.isPending ? copy.confirming : copy.confirm}</button> : null}
        </div>
      </footer>
      {showRevision ? (
        <section aria-label={copy.revisionTitle} className="rubric-revision-panel">
          <h2>{copy.revisionTitle}</h2>
          <label><span>{copy.revisionRubric}</span><textarea required value={revision.originalRubric} onChange={(event) => setRevision((current) => ({ ...current, originalRubric: event.target.value }))} /></label>
          <div className="stage6-score-fields">
            <label><span>{copy.total}</span><input min="0.0001" required step="0.0001" type="number" value={revision.totalScore} onChange={(event) => setRevision((current) => ({ ...current, totalScore: event.target.value }))} /></label>
            <label><span>{copy.step}</span><input min="0.0001" required step="0.0001" type="number" value={revision.scoreStep} onChange={(event) => setRevision((current) => ({ ...current, scoreStep: event.target.value }))} /></label>
          </div>
          <div className="stage6-form-actions"><button className="secondary-button" onClick={() => setShowRevision(false)} type="button">{copy.cancelRevision}</button><button className="primary-button" disabled={revisionMutation.isPending || !revision.originalRubric.trim()} onClick={() => revisionMutation.mutate()} type="button">{revisionMutation.isPending ? copy.savingRevision : copy.saveRevision}</button></div>
        </section>
      ) : null}
    </div>
  );
}
