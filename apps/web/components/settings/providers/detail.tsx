"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

import { ProviderIcon } from "./icons/provider-icon";

import { AccountManager } from "./auth/account-manager";
import { BaseUrl } from "./auth/base-url";
import { Connectivity, type ConnectivityHandle } from "./auth/connectivity";
import { ModelList } from "./model-list";
import { CliInfo, SetupHint } from "./auth/setup-hint";
import styles from "./provider-pane.module.css";
import type { Model, Provider } from "./types";
import { useTranslation } from "@/lib/i18n";
import { confirmAction } from "@/components/ui/confirm-dialog";
import { HoverTip } from "@/components/ui/tooltip";
import { settingsSend } from "@/lib/settings/settings-request";

/** Right-pane detail view for one selected provider. Header + enable
 *  toggle, then a stack of sections: setup hint (optional), API key
 *  (api kind only), base URL, connectivity, and the model list (or
 *  CLI info for CLI providers). */
export function Detail({
  provider,
  onToggle,
  onChanged,
  onDeleted,
}: {
  provider: Provider;
  onToggle: (enabled: boolean) => void;
  onChanged: () => void;
  onDeleted?: () => void;
}) {
  const { text } = useTranslation();

  async function deleteProvider() {
    if (!(await confirmAction({
      title: text(`Delete custom provider "${provider.label}"?`, `删除自定义 Provider “${provider.label}”？`),
      description: text("Its models are removed; any saved API key is kept.", "其模型将被移除；已保存的 API key 会保留。"),
      confirmLabel: text("Delete", "删除"),
      destructive: true,
    }))) return;
    const deleted = await settingsSend(`/api/providers/custom/${encodeURIComponent(provider.id)}`, {
      method: "DELETE",
      failure: text("Could not delete this provider.", "无法删除这个 Provider。"),
    });
    if (deleted === null) return;
    onDeleted?.();
  }
  const subtitle =
    provider.local
      ? text("Local inference server · API key optional", "本地推理服务 · API key 可选")
      : provider.kind === "cli"
      ? text(`CLI runtime - binary: ${provider.cli_binary || "?"}`, `CLI 运行时 - binary：${provider.cli_binary || "?"}`)
      : provider.id === "xai-subscription"
          ? text("Runs on your SuperGrok / X Premium+ subscription — no API key", "用你的 SuperGrok / X Premium+ 订阅 — 无需 API key")
        : provider.api_key_env
          ? text("API key provider", "API key 提供商")
          : text("Subscription required", "需要订阅");

  const [models, setModels] = useState<Model[]>([]);
  const [modelsState, setModelsState] = useState<"loading" | "ready" | "failed">("loading");
  const [modelSearch, setModelSearch] = useState("");
  const [fetchStatus, setFetchStatus] = useState<string | null>(null);
  const [manualId, setManualId] = useState("");
  const [manualBusy, setManualBusy] = useState(false);
  const [contextWindow, setContextWindow] = useState("128000");
  const [maxTokens, setMaxTokens] = useState("8192");
  const [manualError, setManualError] = useState<string | null>(null);
  const connectivityRef = useRef<ConnectivityHandle>(null);

  const reloadModels = useCallback(async () => {
    if (provider.kind === "cli") {
      setModels([]);
      setModelsState("ready");
      return;
    }
    try {
      const r = await fetch(
        `/api/providers/${encodeURIComponent(provider.id)}/models`,
      );
      if (!r.ok) throw new Error(String(r.status));
      const d = await r.json();
      setModels(d.models || []);
      setModelsState("ready");
    } catch {
      setModelsState("failed");
    }
  }, [provider.id, provider.kind]);

  useEffect(() => {
    setModels([]);
    setModelsState("loading");
    reloadModels();
  }, [reloadModels]);

  useEffect(() => {
    const refreshChangedProvider = (event: Event) => {
      const changed = (event as CustomEvent<{ provider?: string }>).detail?.provider;
      if (!changed || changed === provider.id) void reloadModels();
    };
    window.addEventListener("op:provider-models-changed", refreshChangedProvider);
    return () => window.removeEventListener("op:provider-models-changed", refreshChangedProvider);
  }, [provider.id, reloadModels]);

  // After a NEW key is saved: auto-run the connectivity check (its
  // inline ✓/✗ result shows in the Connectivity row, exactly as if the
  // user clicked "Check") and, on success, fetch the model list and
  // refresh it in place. No toasts — the result lives in the panel.
  const autoCheckAndFetch = useCallback(async () => {
    const ok = await connectivityRef.current?.run();
    if (!ok) return;
    try {
      await fetch(`/api/providers/${encodeURIComponent(provider.id)}/fetch-models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } catch { /* ignore — list just won't refresh */ }
    reloadModels();
    onChanged();
  }, [provider.id, reloadModels, onChanged]);

  // Pull the model list from the provider's live /v1/models (or
  // OpenAI-style /models). Shared by the empty-state button below — a
  // provider with no registry rows (every models.dev community entry
  // ships zero) otherwise has no way to populate its list, because the
  // ModelList's own "Fetch models" button only renders once models
  // exist. This is that same fetch, surfaced before the first one lands.
  const fetchModels = useCallback(async () => {
    setFetchStatus(text("Fetching…", "获取中…"));
    try {
      const r = await fetch(
        `/api/providers/${encodeURIComponent(provider.id)}/fetch-models`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
      );
      const d = await r.json();
      if (d.error) {
        setFetchStatus(text("Failed: ", "失败：") + d.error);
        setTimeout(() => setFetchStatus(null), 6_000);
        return;
      }
      setFetchStatus(text(`Fetched ${d.fetched}`, `已获取 ${d.fetched} 个`));
      await reloadModels();
      onChanged();
      setTimeout(() => setFetchStatus(null), 4_000);
    } catch (e) {
      setFetchStatus(text("Failed: ", "失败：") + (e as Error).message);
      setTimeout(() => setFetchStatus(null), 6_000);
    }
  }, [provider.id, reloadModels, onChanged, text]);

  // Custom providers whose /models list is unavailable let the user type a
  // model id by hand. Writes an enabled minimal spec row (source=manual).
  const addManualModel = useCallback(async () => {
    const mid = manualId.trim();
    if (!mid) return;
    setManualBusy(true);
    try {
      const response = await fetch(`/api/providers/${encodeURIComponent(provider.id)}/models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: mid, ...(provider.local ? { context_window: Number(contextWindow), max_tokens: Number(maxTokens) } : {}) }),
      });
      const result = await response.json();
      if (!response.ok || result.error) { setManualError(result.error || text("Could not save the model.", "无法保存模型。")); return; }
      setManualError(null);
      setManualId("");
      await reloadModels();
      onChanged();
    } catch {
      setManualError(text("Could not save the model. Check the connection and try again.", "无法保存模型，请检查连接后重试。"));
    } finally {
      setManualBusy(false);
    }
  }, [manualId, provider.id, provider.local, contextWindow, maxTokens, reloadModels, onChanged]);

  return (
    <div className={`${styles.detailSurface} flex flex-col gap-[16px] min-w-0 p-[16px_20px_20px]`}>
      <div className={styles.detailHeader}>
        <div className={`${styles.detailIcon} w-[40px] h-[40px] flex items-center justify-center`}>
          <ProviderIcon id={provider.id} size={40} />
        </div>
        <div className="flex-1 min-w-0">
          <div className={styles.detailTitle}>{provider.label}</div>
          <div className={styles.detailSubtitle}>{subtitle}</div>
        </div>
        <div className={`${styles.detailHeaderActions} flex items-center shrink-0 gap-[12px]`}>
          <label className={styles.providerEnabledControl}>
            <span className={styles.providerEnabledLabel}>
              {provider.enabled ? text("Enabled", "已启用") : text("Disabled", "已停用")}
            </span>
            <Switch
              checked={provider.enabled}
              onCheckedChange={onToggle}
              aria-label={text("Enable this provider", "启用这个 Provider")}
            />
          </label>
          {provider.custom && (
            <HoverTip label={text("Delete custom provider", "删除自定义 Provider")}>
              <Button
                variant="destructive"
                size="icon"
                aria-label={text("Delete custom provider", "删除自定义 Provider")}
                onClick={deleteProvider}
              >
                <Trash2 />
              </Button>
            </HoverTip>
          )}
        </div>
      </div>

      {provider.setup_hint && (
        <SetupHint hint={provider.setup_hint} configured={!!provider.configured} />
      )}

      {/* ONE management panel for every provider's credentials (P-D). An account
          is a named, switchable credential — a KEY for api-key providers, a
          SIGN-IN for login providers, a provider sign-in.
          Same UI everywhere; only the add flow and account label differ inside.
          See account-manager.tsx. */}
      {(!!provider.api_key_env ||
        (provider.login_methods?.length ?? 0) > 0) && (
        <AccountManager key={`${provider.id}:accounts`} provider={provider} onChanged={autoCheckAndFetch} />
      )}
      {(provider.api_key_env || provider.local) && (
        <BaseUrl key={`${provider.id}:base-url`} provider={provider} onChanged={onChanged} />
      )}
      {/* Connectivity check applies to every HTTP provider, not just
          api-key ones. OAuth providers (openai-codex, gemini-subscription,
          github-copilot, …) need this control too — without it the
          ChatGPT subscription flow has no in-UI way to verify the OAuth
          token survived restart. Backend already handles the auth
          lookup. */}
      {provider.kind === "api" && (
        <Connectivity key={`${provider.id}:check`} ref={connectivityRef} providerId={provider.id} local={provider.local} />
      )}

      {(provider.custom || provider.local) && provider.kind !== "cli" && (
        <div className="flex flex-col gap-[10px]" style={{ display: "grid", gap: 6 }}>
          <div className={styles.detailSectionTitle}>
            <span>{text("Add model by id", "手动添加模型")}</span>
          </div>
          <div className={`${styles.detailRow} flex gap-[10px] items-center`}>
            <Input
              placeholder={text("model id (e.g. my-model)", "模型 id（如 my-model）")}
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addManualModel(); }}
            />
            <Button onClick={addManualModel} disabled={!manualId.trim() || manualBusy}>
              {manualBusy ? text("Adding…", "添加中…") : text("Add", "添加")}
            </Button>
          </div>
          {provider.local && <div className={`${styles.detailRow} flex gap-[10px] items-center`}>
            <label>{text("Context tokens", "上下文 token 数")}<Input type="number" min="1" value={contextWindow} onChange={(event) => setContextWindow(event.target.value)} /></label>
            <label>{text("Output tokens", "最大输出 token 数")}<Input type="number" min="1" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} /></label>
          </div>}
          {manualError && <span role="alert">{manualError}</span>}
          <span style={{ fontSize: "var(--fs-2xs)", color: "var(--text-muted)" }}>
            {text(
              "Add or update a model by its server ID. Set limits to match the server. The model is enabled immediately.",
              "按服务中的模型 ID 添加或更新模型。限制应与服务配置一致。保存后模型会立即启用。",
            )}
          </span>
        </div>
      )}

      {provider.kind === "cli" ? (
        <CliInfo provider={provider} />
      ) : modelsState === "loading" ? null : modelsState === "failed" ? (
        <div className="flex items-center justify-between gap-[10px]">
          <span className={styles.modelCountSummary}>{text("Could not load the model list.", "无法加载模型列表。")}</span>
          <Button variant="elevated" onClick={reloadModels}>{text("Retry", "重试")}</Button>
        </div>
      ) : models.length > 0 ? (
        <ModelList provider={provider} models={models} search={modelSearch} onSearch={setModelSearch} onReload={reloadModels} />
      ) : (
        <div className="flex flex-col gap-[10px]">
          <div className={styles.detailSectionTitle}>
            <span className={styles.modelCountSummary}>
              {provider.supports_fetch
                ? text("No models yet — fetch them from the provider.", "还没有模型 — 从 Provider 拉取。")
                : text("No models in the registry for this provider.", "这个 Provider 在注册表中没有模型。")}
            </span>
            <span className="flex items-center flex-wrap justify-end gap-[6px]">
              {fetchStatus && (
                <span style={{ fontSize: "var(--fs-2xs)", color: "var(--text-muted)" }}>{fetchStatus}</span>
              )}
              {provider.supports_fetch && (
                <Button onClick={fetchModels}>
                  {text("Fetch models", "获取模型")}
                </Button>
              )}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
