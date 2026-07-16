import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import { useAppApi, type AssignmentCreateInput } from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";
import { LocalTextImport } from "./LocalTextImport";

const initialForm: AssignmentCreateInput = {
  title: "",
  instructions: "",
  originalRubric: "",
  totalScore: "",
  scoreStep: "",
};

function decimalParts(value: string) {
  const normalized = value.startsWith(".") ? `0${value}` : value;
  const match = /^(\d+)(?:\.(\d{1,4}))?$/.exec(normalized);
  if (!match) {
    return null;
  }
  return { fraction: match[2] ?? "", whole: match[1] };
}

function isPositiveDecimalMultiple(totalValue: string, stepValue: string) {
  const totalParts = decimalParts(totalValue);
  const stepParts = decimalParts(stepValue);
  if (!totalParts || !stepParts) {
    return false;
  }
  const scale = Math.max(totalParts.fraction.length, stepParts.fraction.length);
  const toScaledInteger = ({ whole, fraction }: { whole: string; fraction: string }) => (
    BigInt(`${whole}${fraction.padEnd(scale, "0")}`)
  );
  const total = toScaledInteger(totalParts);
  const step = toScaledInteger(stepParts);
  return total > 0n && step > 0n && total % step === 0n;
}

const newAssignmentCopy = {
  zh: {
    title: "创建作业",
    intro: "设置题目要求和原始评分标准。",
    name: "作业名称",
    namePlaceholder: "请输入作业名称",
    instructions: "题目要求",
    instructionsPlaceholder: "请输入题目要求",
    rubric: "原始评分标准",
    rubricPlaceholder: "请输入原始评分标准",
    total: "总分",
    step: "评分步长",
    cancel: "取消",
    save: "保存并继续",
    saving: "正在保存…",
    failed: "创建作业失败。",
    scoreInvalid: "总分必须能被评分步长整除。",
  },
  en: {
    title: "Create assignment",
    intro: "Set the prompt and original grading rubric.",
    name: "Assignment name",
    namePlaceholder: "Enter an assignment name",
    instructions: "Prompt",
    instructionsPlaceholder: "Enter the assignment prompt",
    rubric: "Original rubric",
    rubricPlaceholder: "Enter the original rubric",
    total: "Total score",
    step: "Score step",
    cancel: "Cancel",
    save: "Save and continue",
    saving: "Saving…",
    failed: "The assignment could not be created.",
    scoreInvalid: "The total score must be divisible by the score step.",
  },
} as const;

export function NewAssignmentPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { session } = useAuth();
  const api = useAppApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const copy = newAssignmentCopy[language];
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState("");
  const createMutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.createAssignment(session, form);
    },
    onSuccess: async (assignment) => {
      await queryClient.invalidateQueries({ queryKey: ["assignments"] });
      navigate(`/assignments/${assignment.id}/rubric`, { replace: true });
    },
    onError: (mutationError) => {
      setError(mutationError instanceof ApiRequestError ? mutationError.message : copy.failed);
    },
  });

  function updateField(field: keyof AssignmentCreateInput, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isPositiveDecimalMultiple(form.totalScore, form.scoreStep)) {
      setError(copy.scoreInvalid);
      return;
    }
    setError("");
    createMutation.mutate();
  }

  return (
    <div className="page stage6-page new-assignment-page">
      <header className="stage6-form-heading">
        <h1>{copy.title}</h1>
        <p>{copy.intro}</p>
      </header>
      <form className="stage6-form" onSubmit={handleSubmit}>
        <label>
          <span>{copy.name}</span>
          <input
            required
            maxLength={300}
            placeholder={copy.namePlaceholder}
            value={form.title}
            onChange={(event) => updateField("title", event.target.value)}
          />
        </label>
        <div className="stage6-text-field">
          <label>
            <span>{copy.instructions}</span>
            <textarea
              required
              maxLength={100_000}
              placeholder={copy.instructionsPlaceholder}
              value={form.instructions}
              onChange={(event) => updateField("instructions", event.target.value)}
            />
          </label>
          <LocalTextImport
            fieldLabel={copy.instructions}
            language={language}
            onError={setError}
            onText={(value) => updateField("instructions", value)}
          />
        </div>
        <div className="stage6-text-field">
          <label>
            <span>{copy.rubric}</span>
            <textarea
              required
              maxLength={100_000}
              placeholder={copy.rubricPlaceholder}
              value={form.originalRubric}
              onChange={(event) => updateField("originalRubric", event.target.value)}
            />
          </label>
          <LocalTextImport
            fieldLabel={copy.rubric}
            language={language}
            onError={setError}
            onText={(value) => updateField("originalRubric", value)}
          />
        </div>
        <div className="stage6-score-fields">
          <label>
            <span>{copy.total}</span>
            <input required min="0.0001" step="0.0001" type="number" value={form.totalScore} onChange={(event) => updateField("totalScore", event.target.value)} />
          </label>
          <label>
            <span>{copy.step}</span>
            <input required min="0.0001" step="0.0001" type="number" value={form.scoreStep} onChange={(event) => updateField("scoreStep", event.target.value)} />
          </label>
        </div>
        {error ? <p className="form-message form-message--error" role="alert">{error}</p> : null}
        <div className="stage6-form-actions">
          <Link className="secondary-button" to="/assignments">{copy.cancel}</Link>
          <button className="primary-button" disabled={createMutation.isPending} type="submit">
            {createMutation.isPending ? copy.saving : copy.save}
          </button>
        </div>
      </form>
    </div>
  );
}
