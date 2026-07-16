import { useEffect, useState, type FormEvent } from "react";

import {
  useAppApi,
  type TeacherAccount,
} from "../../../features/api/AppApiContext";
import { useAuth } from "../../../features/auth/AuthContext";
import { Icon } from "../../../app/icons";

const statusText = {
  invited: "待首次登录",
  active: "正常",
  disabled: "已停用",
} as const;

function formatInviteTime(value: string | null) {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function AdminUsersPage() {
  const api = useAppApi();
  const { session } = useAuth();
  const [accounts, setAccounts] = useState<TeacherAccount[]>([]);
  const [isInviteOpen, setIsInviteOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) {
      return;
    }
    let isActive = true;

    void api
      .listTeachers(session)
      .then((teachers) => {
        if (isActive) {
          setAccounts(teachers);
        }
      })
      .catch(() => {
        if (isActive) {
          setError("教师账户加载失败，请刷新页面重试。");
        }
      })
      .finally(() => {
        if (isActive) {
          setIsLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [api, session]);

  async function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      const invited = await api.inviteTeacher(session, {
        displayName: String(data.get("displayName") ?? "").trim(),
        email: String(data.get("email") ?? "").trim(),
      });
      setAccounts((current) => [...current, invited]);
      setIsInviteOpen(false);
    } catch {
      setError("邀请发送失败，请确认邮箱未被邀请后重试。");
    }
  }

  async function changeStatus(account: TeacherAccount) {
    if (!session || account.status === "invited") {
      return;
    }
    setPendingId(account.id);
    setError("");
    try {
      if (account.status === "active") {
        await api.disableTeacher(session, account.id);
      } else {
        await api.enableTeacher(session, account.id);
      }
      setAccounts((current) =>
        current.map((item) =>
          item.id === account.id
            ? { ...item, status: item.status === "active" ? "disabled" : "active" }
            : item,
        ),
      );
    } catch {
      setError("账户状态修改失败，列表未更改。");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="page admin-users-page">
      <section className="admin-users-header">
        <div>
          <h1>教师账户管理</h1>
          <p>邀请并管理教师登录权限。</p>
        </div>
        <button
          className="primary-button admin-invite-button"
          onClick={() => setIsInviteOpen(true)}
          type="button"
        >
          <Icon name="plus" />
          邀请教师
        </button>
      </section>

      {error ? (
        <p className="form-message form-message--error admin-users-message" role="alert">
          {error}
        </p>
      ) : null}

      <section className="account-table-wrap" aria-label="教师账户列表">
        <table className="account-table">
          <thead>
            <tr>
              <th scope="col">教师</th>
              <th scope="col">状态</th>
              <th scope="col">邀请时间</th>
              <th scope="col">操作</th>
            </tr>
          </thead>
          <tbody>
            {accounts.map((account) => (
              <tr key={account.id}>
                <td>
                  <strong>{account.display_name}</strong>
                  <span>{account.email}</span>
                </td>
                <td>
                  <span className={`account-status account-status--${account.status}`}>
                    {statusText[account.status]}
                  </span>
                </td>
                <td>{formatInviteTime(account.invited_at)}</td>
                <td>
                  {account.status === "invited" ? (
                    <span aria-label="暂无操作">—</span>
                  ) : (
                    <button
                      className="table-action"
                      disabled={pendingId === account.id}
                      onClick={() => void changeStatus(account)}
                      type="button"
                    >
                      {pendingId === account.id
                        ? "处理中…"
                        : account.status === "active"
                          ? "停用"
                          : "启用"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {isLoading ? <p className="table-empty">正在加载教师账户…</p> : null}
        {!isLoading && accounts.length === 0 ? (
          <p className="table-empty">还没有教师账户。</p>
        ) : null}
      </section>

      {isInviteOpen ? (
        <div className="invite-backdrop" onMouseDown={() => setIsInviteOpen(false)}>
          <section
            aria-labelledby="invite-title"
            aria-modal="true"
            className="invite-panel"
            onMouseDown={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="invite-panel__header">
              <h2 id="invite-title">邀请教师</h2>
              <button
                aria-label="关闭邀请窗口"
                className="icon-button"
                onClick={() => setIsInviteOpen(false)}
                type="button"
              >
                <Icon name="close" />
              </button>
            </div>
            <form className="invite-form" onSubmit={handleInvite}>
              <label htmlFor="invite-name">姓名</label>
              <input id="invite-name" name="displayName" placeholder="请输入姓名" required />
              <label htmlFor="invite-email">邮箱</label>
              <input
                id="invite-email"
                name="email"
                placeholder="请输入邮箱"
                required
                type="email"
              />
              <div className="invite-form__actions">
                <button
                  className="secondary-button"
                  onClick={() => setIsInviteOpen(false)}
                  type="button"
                >
                  取消
                </button>
                <button className="primary-button" type="submit">
                  发送邀请
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
