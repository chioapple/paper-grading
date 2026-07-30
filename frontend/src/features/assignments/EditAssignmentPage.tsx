import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import {
  useAppApi,
  type AssignmentDetail,
  type AssignmentUpdateInput,
} from "../api/AppApiContext";
import { ApiRequestError } from "../api/httpAppApi";
import { useAuth } from "../auth/AuthContext";
import { LocalTextImport } from "./LocalTextImport";

const editAssignmentCopy = {
  zh: {
    title: "编辑作业",
    intro: "只有尚未确认评分标准的草稿作业可以修改。",
    name: "作业名称",
    instructions: "题目要求",
    save: "保存修改",
    saving: "正在保存…",
    cancel: "取消",
    loading: "正在加载作业…",
    loadFailed: "暂时无法加载作业。",
    immutable: "评分标准已确认的作业不可直接修改，请新建作业以保留已有评分记录。",
    failed: "作业修改失败。",
  },
  en: {
    title: "Edit assignment",
    intro: "Only a draft assignment whose rubric is not confirmed can be edited.",
    name: "Assignment name",
    instructions: "Prompt",
    save: "Save changes",
    saving: "Saving…",
    cancel: "Cancel",
    loading: "Loading assignment…",
    loadFailed: "The assignment could not be loaded.",
    immutable: "An assignment with a confirmed rubric cannot be edited directly. Create a new assignment to preserve existing grading records.",
    failed: "The assignment could not be updated.",
  },
} as const;

function EditAssignmentForm({
  assignment,
  language,
}: {
  assignment: AssignmentDetail;
  language: "zh" | "en";
}) {
  const { session } = useAuth();
  const api = useAppApi();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const copy = editAssignmentCopy[language];
  const [form, setForm] = useState<AssignmentUpdateInput>({
    title: assignment.title,
    instructions: assignment.instructions,
  });
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.updateAssignment(session, assignment.id, form);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["assignments"] }),
        queryClient.invalidateQueries({ queryKey: ["assignment", assignment.id] }),
      ]);
      navigate("/assignments", { replace: true });
    },
    onError: (mutationError) => {
      setError(mutationError instanceof ApiRequestError ? mutationError.message : copy.failed);
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    mutation.mutate();
  }

  return (
    <form className="stage6-form" onSubmit={submit}>
      <label>
        <span>{copy.name}</span>
        <input
          maxLength={300}
          onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
          required
          value={form.title}
        />
      </label>
      <div className="stage6-text-field">
        <label>
          <span>{copy.instructions}</span>
          <textarea
            maxLength={100_000}
            onChange={(event) => setForm((current) => ({ ...current, instructions: event.target.value }))}
            required
            value={form.instructions}
          />
        </label>
        <LocalTextImport
          fieldLabel={copy.instructions}
          language={language}
          onError={setError}
          onText={(instructions) => setForm((current) => ({ ...current, instructions }))}
        />
      </div>
      {error ? <p className="form-message form-message--error" role="alert">{error}</p> : null}
      <div className="stage6-form-actions">
        <Link className="secondary-button" to="/assignments">{copy.cancel}</Link>
        <button className="primary-button" disabled={mutation.isPending} type="submit">
          {mutation.isPending ? copy.saving : copy.save}
        </button>
      </div>
    </form>
  );
}

export function EditAssignmentPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { assignmentId = "" } = useParams();
  const { session } = useAuth();
  const api = useAppApi();
  const copy = editAssignmentCopy[language];
  const query = useQuery({
    queryKey: ["assignment", assignmentId],
    enabled: Boolean(session && assignmentId),
    queryFn: () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.getAssignment(session, assignmentId);
    },
  });

  if (query.isPending) {
    return <div className="page stage6-page"><p className="table-empty">{copy.loading}</p></div>;
  }
  if (query.isError || !query.data) {
    return <div className="page stage6-page"><p className="form-message form-message--error" role="alert">{copy.loadFailed}</p></div>;
  }

  return (
    <div className="page stage6-page new-assignment-page">
      <header className="stage6-form-heading">
        <h1>{copy.title}</h1>
        <p>{copy.intro}</p>
      </header>
      {query.data.status === "draft" ? (
        <EditAssignmentForm
          assignment={query.data}
          key={`${query.data.id}-${query.data.updated_at}`}
          language={language}
        />
      ) : (
        <>
          <p className="form-message form-message--error" role="alert">{copy.immutable}</p>
          <div className="stage6-form-actions">
            <Link className="secondary-button" to="/assignments">{copy.cancel}</Link>
          </div>
        </>
      )}
    </div>
  );
}
