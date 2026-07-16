import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../../app/AppShell";
import { Icon } from "../../app/icons";
import { useAppApi, type AssignmentSummary } from "../api/AppApiContext";
import { useAuth } from "../auth/AuthContext";

const assignmentsCopy = {
  zh: {
    title: "作业",
    intro: "创建并管理作文题目与评分标准。",
    create: "创建作业",
    name: "作业名称",
    status: "状态",
    rubric: "评分标准",
    updated: "最近更新",
    action: "操作",
    loading: "正在加载作业…",
    loadFailed: "暂时无法加载作业。",
    emptyTitle: "还没有作业",
    emptyBody: "创建第一个作业，开始设置题目与评分标准。",
    continue: "继续设置",
    view: "查看评分标准",
    upload: "上传论文",
    restore: "恢复",
    draft: "草稿",
    ready: "可批改",
    archived: "已归档",
    confirmed: "已确认",
    archive: "归档",
    actionFailed: "更新作业状态失败。",
  },
  en: {
    title: "Assignments",
    intro: "Create and manage prompts and grading rubrics.",
    create: "Create assignment",
    name: "Assignment",
    status: "Status",
    rubric: "Rubric",
    updated: "Updated",
    action: "Action",
    loading: "Loading assignments…",
    loadFailed: "Assignments could not be loaded.",
    emptyTitle: "No assignments yet",
    emptyBody: "Create your first assignment and set its rubric.",
    continue: "Continue setup",
    view: "View rubric",
    upload: "Upload papers",
    restore: "Restore",
    draft: "Draft",
    ready: "Ready",
    archived: "Archived",
    confirmed: "Confirmed",
    archive: "Archive",
    actionFailed: "The assignment status could not be updated.",
  },
} as const;

function rubricLabel(assignment: AssignmentSummary, language: "zh" | "en") {
  const copy = assignmentsCopy[language];
  if (assignment.current_draft_version !== null) {
    return `${copy.draft} v${assignment.current_draft_version}`;
  }
  if (assignment.current_confirmed_version !== null) {
    return `${copy.confirmed} v${assignment.current_confirmed_version}`;
  }
  return "—";
}

function assignmentAction(assignment: AssignmentSummary, language: "zh" | "en") {
  const copy = assignmentsCopy[language];
  if (assignment.status === "archived") {
    return copy.restore;
  }
  return assignment.current_draft ? copy.continue : copy.view;
}

export function AssignmentsPage() {
  const { language } = useOutletContext<AppOutletContext>();
  const { session } = useAuth();
  const api = useAppApi();
  const queryClient = useQueryClient();
  const copy = assignmentsCopy[language];
  const [error, setError] = useState("");
  const assignmentsQuery = useQuery({
    queryKey: ["assignments"],
    enabled: Boolean(session),
    queryFn: () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.listAssignments(session);
    },
  });
  const assignments = assignmentsQuery.data ?? [];
  const statusMutation = useMutation({
    mutationFn: async ({ assignmentId, status }: { assignmentId: string; status: "draft" | "archived" }) => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.updateAssignmentStatus(session, assignmentId, status);
    },
    onSuccess: async () => {
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["assignments"] });
    },
    onError: () => setError(copy.actionFailed),
  });

  return (
    <div className="page stage6-page assignments-index">
      <section className="stage6-page-header">
        <div>
          <h1>{copy.title}</h1>
          <p>{copy.intro}</p>
        </div>
        <Link className="primary-button stage6-create-link" to="/assignments/new">
          <Icon name="plus" />
          <span>{copy.create}</span>
        </Link>
      </section>

      {assignmentsQuery.isPending ? <p className="table-empty">{copy.loading}</p> : null}
      {assignmentsQuery.isError ? (
        <p className="form-message form-message--error" role="alert">{copy.loadFailed}</p>
      ) : null}
      {error ? <p className="form-message form-message--error" role="alert">{error}</p> : null}
      {!assignmentsQuery.isPending && !assignmentsQuery.isError && assignments.length === 0 ? (
        <section className="empty-state">
          <div className="empty-state__icon"><Icon name="inbox" /></div>
          <h2>{copy.emptyTitle}</h2>
          <p>{copy.emptyBody}</p>
          <Link className="primary-button stage6-create-link" to="/assignments/new">
            <Icon name="plus" />
            <span>{copy.create}</span>
          </Link>
        </section>
      ) : null}
      {assignments.length > 0 ? (
        <section className="account-table-wrap stage6-table-wrap" aria-label={copy.title}>
          <table className="account-table stage6-table">
            <thead><tr>
              <th scope="col">{copy.name}</th>
              <th scope="col">{copy.status}</th>
              <th scope="col">{copy.rubric}</th>
              <th scope="col">{copy.updated}</th>
              <th scope="col">{copy.action}</th>
            </tr></thead>
            <tbody>
              {assignments.map((assignment) => (
                <tr key={assignment.id}>
                  <td data-label={copy.name}><strong>{assignment.title}</strong></td>
                  <td data-label={copy.status}>{copy[assignment.status]}</td>
                  <td data-label={copy.rubric}>{rubricLabel(assignment, language)}</td>
                  <td data-label={copy.updated}>
                    {new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en", {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(assignment.updated_at))}
                  </td>
                  <td data-label={copy.action}>
                    <div className="stage6-row-actions">
                      {assignment.status === "archived" ? (
                        <button aria-label={`${copy.restore} ${assignment.title}`} className="stage6-row-link" disabled={statusMutation.isPending} onClick={() => statusMutation.mutate({ assignmentId: assignment.id, status: "draft" })} type="button">{copy.restore}</button>
                      ) : (
                        <>
                          {assignment.status === "ready" ? (
                            <Link className="stage6-row-link" to={`/assignments/${assignment.id}/submissions`}>
                              {copy.upload}
                            </Link>
                          ) : null}
                          <Link className="stage6-row-link" to={`/assignments/${assignment.id}/rubric`}>
                            {assignmentAction(assignment, language)}
                          </Link>
                          <button aria-label={`${copy.archive} ${assignment.title}`} className="stage6-row-link stage6-row-link--muted" disabled={statusMutation.isPending} onClick={() => statusMutation.mutate({ assignmentId: assignment.id, status: "archived" })} type="button">{copy.archive}</button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}
