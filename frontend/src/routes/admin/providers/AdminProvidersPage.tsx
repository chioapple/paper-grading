import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useOutletContext } from "react-router-dom";

import type { AppOutletContext } from "../../../app/AppShell";
import { Icon } from "../../../app/icons";
import {
  useAppApi,
  type ProviderConfig,
  type ProviderConfigInput,
  type ProviderType,
} from "../../../features/api/AppApiContext";
import { ApiRequestError } from "../../../features/api/httpAppApi";
import { useAuth } from "../../../features/auth/AuthContext";
import { providerCopy } from "./providerCopy";

const providerLabels: Record<ProviderType, string> = {
  deepseek: "DeepSeek",
  kimi: "Kimi",
  glm: "GLM",
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
  openai_compatible: "OpenAI Compatible",
};

const officialBaseUrls: Partial<Record<ProviderType, string>> = {
  deepseek: "https://api.deepseek.com",
  kimi: "https://api.moonshot.cn/v1",
  glm: "https://open.bigmodel.cn/api/paas/v4",
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com",
  gemini: "https://generativelanguage.googleapis.com",
};

type FormState = {
  providerType: ProviderType;
  name: string;
  baseUrl: string;
  apiKey: string;
  allowedModelsText: string;
  defaultModel: string;
  timeoutSeconds: string;
  maxConcurrency: string;
  monthlyBudget: string;
};

const emptyForm: FormState = {
  providerType: "deepseek",
  name: "",
  baseUrl: officialBaseUrls.deepseek ?? "",
  apiKey: "",
  allowedModelsText: "",
  defaultModel: "",
  timeoutSeconds: "60",
  maxConcurrency: "2",
  monthlyBudget: "",
};

function formFromProvider(provider: ProviderConfig): FormState {
  return {
    providerType: provider.provider_type,
    name: provider.name,
    baseUrl: provider.base_url,
    apiKey: "",
    allowedModelsText: provider.allowed_models.join("\n"),
    defaultModel: provider.default_model ?? "",
    timeoutSeconds: provider.timeout_seconds,
    maxConcurrency: String(provider.max_concurrency),
    monthlyBudget: provider.monthly_budget ?? "",
  };
}

function parseModels(value: string) {
  return [...new Set(value.split(/[\n,]/).map((model) => model.trim()).filter(Boolean))];
}

function toInput(form: FormState): ProviderConfigInput {
  return {
    providerType: form.providerType,
    name: form.name.trim(),
    baseUrl: form.baseUrl.trim().replace(/\/$/, ""),
    apiKey: form.apiKey.trim() || undefined,
    allowedModels: parseModels(form.allowedModelsText),
    defaultModel: form.defaultModel.trim(),
    timeoutSeconds: form.timeoutSeconds,
    maxConcurrency: Number(form.maxConcurrency),
    monthlyBudget: form.monthlyBudget.trim() || null,
  };
}

function safeErrorMessage(error: unknown, fallback: string) {
  return error instanceof ApiRequestError ? error.message : fallback;
}

export function AdminProvidersPage() {
  const api = useAppApi();
  const { session } = useAuth();
  const { language } = useOutletContext<AppOutletContext>();
  const queryClient = useQueryClient();
  const text = providerCopy[language];
  const [editing, setEditing] = useState<ProviderConfig | "new" | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  const providersQuery = useQuery({
    queryKey: ["admin-providers"],
    enabled: Boolean(session),
    queryFn: () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      return api.listProviders(session);
    },
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        throw new Error("登录会话不存在");
      }
      const input = toInput(form);
      if (editing === "new") {
        if (!input.apiKey) {
          throw new Error("API Key 不能为空");
        }
        return api.createProvider(session, { ...input, apiKey: input.apiKey });
      }
      if (!editing) {
        throw new Error("供应商配置不存在");
      }
      return api.updateProvider(session, editing.id, input);
    },
    onSuccess: async () => {
      setEditing(null);
      setError("");
      await queryClient.invalidateQueries({ queryKey: ["admin-providers"] });
    },
    onError: (mutationError) => setError(safeErrorMessage(mutationError, text.saveFailed)),
  });

  function openCreate() {
    setForm({ ...emptyForm });
    setEditing("new");
    setError("");
    setMessage("");
  }

  function openEdit(provider: ProviderConfig) {
    setForm(formFromProvider(provider));
    setEditing(provider);
    setError("");
    setMessage("");
  }

  function changeProviderType(providerType: ProviderType) {
    setForm((current) => ({
      ...current,
      providerType,
      baseUrl: officialBaseUrls[providerType] ?? current.baseUrl,
    }));
  }

  async function handleAction(provider: ProviderConfig, action: "test" | "enable" | "disable") {
    if (!session) {
      return;
    }
    setPendingId(provider.id);
    setError("");
    setMessage("");
    try {
      if (action === "test") {
        await api.testProvider(session, provider.id);
        setMessage(text.testSucceeded);
      } else if (action === "enable") {
        await api.enableProvider(session, provider.id);
      } else {
        await api.disableProvider(session, provider.id);
      }
      await queryClient.invalidateQueries({ queryKey: ["admin-providers"] });
    } catch (actionError) {
      setError(safeErrorMessage(actionError, text.actionFailed));
    } finally {
      setPendingId(null);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    const input = toInput(form);
    if (!input.allowedModels.includes(input.defaultModel)) {
      setError(text.modelInvalid);
      return;
    }
    setError("");
    saveMutation.mutate();
  }

  const providers = providersQuery.data ?? [];

  return (
    <div className="page admin-providers-page">
      <section className="admin-users-header">
        <div>
          <h1>{text.title}</h1>
          <p>{text.intro}</p>
        </div>
        <button className="primary-button admin-invite-button" onClick={openCreate} type="button">
          <Icon name="plus" />
          {text.add}
        </button>
      </section>

      {providersQuery.isError || error ? (
        <p className="form-message form-message--error admin-users-message" role="alert">
          {error || text.loadFailed}
        </p>
      ) : null}
      {message ? <p className="provider-message" role="status">{message}</p> : null}

      {providersQuery.isPending ? <p className="table-empty">{text.loading}</p> : null}
      {!providersQuery.isPending && !providers.length ? (
        <p className="table-empty provider-empty">{text.empty}</p>
      ) : null}
      {providers.length ? (
        <section className="account-table-wrap" aria-label={text.title}>
          <table className="account-table provider-table">
            <thead>
              <tr>
                <th scope="col">{text.provider}</th>
                <th scope="col">{text.models}</th>
                <th scope="col">{text.limits}</th>
                <th scope="col">{text.state}</th>
                <th scope="col">{text.actions}</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((provider) => {
                const isPending = pendingId === provider.id;
                return (
                  <tr key={provider.id}>
                    <td data-label={text.provider}>
                      <strong>{provider.name}</strong>
                      <span>{providerLabels[provider.provider_type]} · {provider.base_url}</span>
                      <small className={provider.api_key_configured ? "provider-ok" : "provider-warning"}>
                        {provider.api_key_configured ? text.keyReady : text.keyMissing}
                      </small>
                    </td>
                    <td data-label={text.models}>
                      <strong>{provider.default_model ?? "—"}</strong>
                      <span>{provider.allowed_models.join(", ")}</span>
                    </td>
                    <td data-label={text.limits}>
                      <span>{provider.timeout_seconds}s · ×{provider.max_concurrency}</span>
                      <span>{provider.monthly_budget ? `${provider.monthly_budget}/月` : "—"}</span>
                    </td>
                    <td data-label={text.state}>
                      <span className={`account-status account-status--${provider.status}`}>
                        {text[provider.status]}
                      </span>
                      <span>{provider.configuration_tested ? text.tested : text.untested}</span>
                    </td>
                    <td data-label={text.actions}>
                      <div className="provider-actions">
                        <button className="table-action" disabled={isPending} onClick={() => openEdit(provider)} type="button">
                          {text.edit}
                        </button>
                        <button className="table-action" disabled={isPending} onClick={() => void handleAction(provider, "test")} type="button">
                          {isPending ? text.working : text.test}
                        </button>
                        {provider.status === "enabled" ? (
                          <button className="table-action" disabled={isPending} onClick={() => void handleAction(provider, "disable")} type="button">
                            {text.disable}
                          </button>
                        ) : (
                          <button className="table-action" disabled={isPending || !provider.can_enable} onClick={() => void handleAction(provider, "enable")} type="button">
                            {text.enable}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      ) : null}

      {editing ? (
        <div className="invite-backdrop provider-backdrop">
          <section aria-labelledby="provider-dialog-title" aria-modal="true" className="invite-panel provider-panel" role="dialog">
            <div className="invite-panel__header">
              <h2 id="provider-dialog-title">{editing === "new" ? text.createTitle : text.editTitle}</h2>
              <button aria-label={text.close} className="icon-button" onClick={() => setEditing(null)} type="button">
                <Icon name="close" />
              </button>
            </div>
            <form className="provider-form" onSubmit={handleSubmit}>
              <label htmlFor="provider-type">{text.providerType}</label>
              <select id="provider-type" value={form.providerType} onChange={(event) => changeProviderType(event.target.value as ProviderType)}>
                {Object.entries(providerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>

              <label htmlFor="provider-name">{text.name}</label>
              <input id="provider-name" maxLength={120} onChange={(event) => setForm({ ...form, name: event.target.value })} required value={form.name} />

              <label htmlFor="provider-url">{text.baseUrl}</label>
              <input disabled={form.providerType !== "openai_compatible"} id="provider-url" onChange={(event) => setForm({ ...form, baseUrl: event.target.value })} required type="url" value={form.baseUrl} />

              <label htmlFor="provider-key">{text.apiKey}</label>
              <input autoComplete="new-password" id="provider-key" onChange={(event) => setForm({ ...form, apiKey: event.target.value })} required={editing === "new"} type="password" value={form.apiKey} />
              <small>{editing === "new" ? text.apiKeyCreateHint : text.apiKeyEditHint}</small>

              <label htmlFor="provider-models">{text.allowedModels}</label>
              <textarea id="provider-models" onChange={(event) => setForm({ ...form, allowedModelsText: event.target.value })} required rows={4} value={form.allowedModelsText} />
              <small>{text.allowedModelsHint}</small>

              <label htmlFor="provider-default-model">{text.defaultModel}</label>
              <input id="provider-default-model" onChange={(event) => setForm({ ...form, defaultModel: event.target.value })} required value={form.defaultModel} />

              <div className="provider-form__grid">
                <div>
                  <label htmlFor="provider-timeout">{text.timeout}</label>
                  <input id="provider-timeout" max="300" min="0.001" onChange={(event) => setForm({ ...form, timeoutSeconds: event.target.value })} required step="0.001" type="number" value={form.timeoutSeconds} />
                </div>
                <div>
                  <label htmlFor="provider-concurrency">{text.concurrency}</label>
                  <input id="provider-concurrency" max="100" min="1" onChange={(event) => setForm({ ...form, maxConcurrency: event.target.value })} required type="number" value={form.maxConcurrency} />
                </div>
                <div>
                  <label htmlFor="provider-budget">{text.budget}</label>
                  <input id="provider-budget" min="0" onChange={(event) => setForm({ ...form, monthlyBudget: event.target.value })} step="0.01" type="number" value={form.monthlyBudget} />
                </div>
              </div>

              <div className="invite-form__actions">
                <button className="secondary-button" onClick={() => setEditing(null)} type="button">{text.cancel}</button>
                <button className="primary-button" disabled={saveMutation.isPending} type="submit">
                  {saveMutation.isPending ? text.saving : text.save}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
