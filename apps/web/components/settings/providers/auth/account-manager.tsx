"use client";

import { Reorder, useDragControls } from "framer-motion";
import { GripVertical, KeyRound, Pencil, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { HoverTip } from "@/components/ui/tooltip";
import { Switch } from "@/components/ui/switch";
import { useTranslation } from "@/lib/i18n";
import { normalizeSecretReplacement } from "@/lib/net/auth/secret-replacement";

import { ProviderLogin } from "./provider-login";
import { settingsSend } from "@/lib/settings/settings-request";
import { confirmAction } from "@/components/ui/confirm-dialog";
import { SimpleSelect } from "@/components/ui/select";
import styles from "../provider-pane.module.css";
import type { Provider, ProviderAccountView } from "../types";

/** ONE management panel for every provider's accounts. An *account* is a profile
 *  holding one credential. EVERY provider uses the same account-row structure;
 *  only the left content differs — api-key shows a masked key with an explicit
 *  replacement action, while login shows the account email. Right-hand
 *  controls (status · Validate · active · Remove) use fixed columns while the
 *  detail pane is wide and reflow into additional rows when it is narrow. The
 *  active control is a single
 *  toggle: it shows the account requests run on — the pinned one, else the
 *  fallback account, whose switch stays on until another is chosen. A drag handle (≥2 accounts) sets the rotation priority.
 *  See docs/design/unified-account-management.md / the plan file. */

interface State {
  accounts: ProviderAccountView[];
  active: string;
  pinned?: string;
  rotation: boolean;
  strategy: string;
  strategies: string[];
  add_mode: "api_key" | "login";
}

const JSON_HEADERS = { "Content-Type": "application/json" };

/** Send one account change; a refused or lost request tells the user. */
async function postAccounts(
  url: string,
  body: unknown,
  text: (en: string, zh: string) => string,
): Promise<boolean> {
  const failure = text("Could not change this account. Try again.", "无法更改这个账号，请重试。");
  return (await settingsSend(url, { body, failure })) !== null;
}

function statusTone(status: string): string {
  if (status === "valid") return styles.valid;
  if (status === "rate_limited" || status === "valid_model_unavailable") return styles.warn;
  if (status === "billing_blocked" || status === "valid_no_balance"
      || status === "invalid_credential" || status === "needs_reauth" || status === "revoked") {
    return styles.error;
  }
  return "";
}

/** Literal status text — the key is either usable or stopped for a reason. */
function statusLabel(status: string, text: (en: string, zh: string) => string): string {
  switch (status) {
    case "valid": return text("valid", "有效");
    case "rate_limited": return text("rate limited", "限流中");
    case "billing_blocked":
    case "valid_no_balance": return text("out of credits", "欠费停用");
    case "valid_model_unavailable": return text("model unavailable", "模型不可用");
    case "needs_reauth": return text("needs re-auth", "需重新验证");
    case "invalid_credential": return text("invalid key", "密钥无效");
    case "revoked": return text("revoked", "已失效");
    case "unknown": return text("unknown", "未知");
    case "checking": return text("Checking", "验证中");
    case "missing": return text("not configured", "未配置");
    default: return status;
  }
}

function AccountUseToggle({ active, fixed = false, rotation, onActivate, onDeactivate }: {
  active: boolean;
  /** In use as the fallback account: choosing another account is the way
   *  to stop using it, so its switch stays on. */
  fixed?: boolean;
  rotation: boolean;
  onActivate: () => void;
  onDeactivate: () => void;
}) {
  const { text } = useTranslation();
  const label = rotation
    ? text("Include in rotation", "加入轮询")
    : text("Use this account for requests", "使用这个账号处理请求");
  return (
    <div
      className={styles.acctUseRow}
      data-tip={fixed ? text("Requests use this account until you choose another one", "选好其他账号之前，请求都用这个账号") : undefined}
    >
      <Switch
        checked={active}
        disabled={fixed}
        onCheckedChange={(checked) => checked ? onActivate() : onDeactivate()}
        aria-label={label}
      />
      <span>{label}</span>
    </div>
  );
}

function AccountRow({
  provider, account, multi, rotation, onChanged, refresh, onCommit,
}: {
  provider: string;
  account: ProviderAccountView;
  multi: boolean;
  rotation: boolean;
  onChanged?: () => void;
  refresh: () => void;
  onCommit: () => void;
}) {
  const { text } = useTranslation();
  const controls = useDragControls();
  const base = `/api/providers/${encodeURIComponent(provider)}/accounts`;

  const [renaming, setRenaming] = useState(false);
  const [renameVal, setRenameVal] = useState(account.label || account.name);
  const [editingKey, setEditingKey] = useState(false);
  const [replacement, setReplacement] = useState("");
  const [vres, setVres] = useState<{ status: string; detail?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const validate = useCallback(async (opts?: { ping?: boolean }) => {
    setVres({ status: "checking" });
    try {
      const qs = opts?.ping ? "?ping=true" : "";
      const d = await fetch(`${base}/${encodeURIComponent(account.id)}/validate${qs}`, { method: "POST" }).then((r) => r.json());
      const status = typeof d.status === "string" && d.status ? d.status : "unknown";
      setVres({ status, detail: d.detail || d.error });
    } catch { setVres({ status: "unknown" }); }
  }, [base, account.id]);

  // On-mount: layer-1 only (do not spend tokens). Explicit click pings.
  useEffect(() => { void validate(); }, [validate]);

  async function doRename() {
    const nv = renameVal.trim();
    setRenaming(false);
    if (!nv || nv === (account.label || account.name)) return;
    // A refused rename (name taken, invalid characters) answers 4xx and leaves
    // the account named as it was — surface it instead of showing the new name.
    const r = await fetch(`${base}/rename`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ id: account.id, name: nv }) });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      setVres({ status: "unknown", detail: d.error });
    }
    refresh();
  }
  async function update() {
    const v = normalizeSecretReplacement(replacement, account.masked_key);
    if (v === null) return;
    setBusy(true);
    try {
      const d = await fetch(`${base}/${encodeURIComponent(account.id)}/update`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ api_key: v, validate: true }) }).then((r) => r.json());
      if (d.ok) {
        setEditingKey(false);
        setReplacement("");
        await refresh();
        onChanged?.();
        void validate({ ping: true });
      } else {
        setVres({ status: "invalid_credential", detail: d.error });
      }
    } catch {
      setVres({ status: "unknown" });
    } finally {
      setBusy(false);
    }
  }
  function startEdit() { setReplacement(""); setEditingKey(true); }
  function cancelEdit() { setReplacement(""); setEditingKey(false); }
  async function activate() {
    await postAccounts(`${base}/use`, { id: account.id }, text);
    refresh();
  }
  async function deactivate() {
    await postAccounts(`${base}/use`, { id: "" }, text);
    refresh();
  }
  // Rotation ON: independent per-account on/off (several can be on at once).
  async function setEnabled(enabled: boolean) {
    await postAccounts(`${base}/enabled`, { id: account.id, enabled }, text);
    refresh();
  }
  async function remove() {
    if (!(await confirmAction({
      title: text(`Remove "${account.label || account.name}"?`, `删除“${account.label || account.name}”？`),
      description: text("Its saved key or sign-in is deleted from this computer.", "这台电脑上保存的密钥或登录信息会被删除。"),
      confirmLabel: text("Remove", "删除"),
      destructive: true,
    }))) return;
    if (await postAccounts(`${base}/remove`, { id: account.id }, text)) {
      refresh();
      onChanged?.();
    }
  }

  const status = vres?.status ?? "checking";
  const statusText = status === "checking" ? text("Checking", "验证中") : statusLabel(status, text);
  const validateLabel = `${statusText}. ${text("Validate account", "验证账号")}`;

  return (
    <Reorder.Item value={account} dragListener={false} dragControls={controls}
      className={styles.acctRow} onDragEnd={onCommit}
      whileDrag={{ backgroundColor: "var(--bg-hover)", boxShadow: "var(--shadow)", zIndex: 5 }}
      transition={{ type: "spring", stiffness: 600, damping: 40 }}>
      <div className={`${styles.acctCardHeader} flex items-center gap-[6px] min-w-0 mb-[10px]`}>
        {multi && (
          <span className={styles.dragHandle} onPointerDown={(e) => controls.start(e)} style={{ touchAction: "none" }}>
            <GripVertical size={14} />
          </span>
        )}
        {renaming ? (
          <Input className={styles.acctRenameInput} autoFocus value={renameVal}
            aria-label={text("Account name", "账号名称")}
            onChange={(e) => setRenameVal(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") doRename(); if (e.key === "Escape") setRenaming(false); }}
            onBlur={doRename} />
        ) : (
          <span className="inline-flex items-center gap-[4px] min-w-0">
            <span className={styles.acctNameText}>{account.label || account.name}</span>
            {/* Keep rename and cancel controls on the same compact icon size. */}
            <HoverTip label={text("Rename", "重命名")}><Button type="button" variant="ghost" size="icon-xs"
              aria-label={text("Rename account", "重命名账号")}
              onClick={() => { setRenameVal(account.label || account.name); setRenaming(true); }}>
              <Pencil size={16} />
            </Button></HoverTip>
          </span>
        )}

        <HoverTip label={vres?.detail || text("Validate account", "验证账号")}>
        <button
          type="button"
          className={`${styles.acctStatusButton} ${statusTone(status)}`}
          onClick={() => { void validate({ ping: true }); }}
          aria-label={validateLabel}
          aria-busy={status === "checking"}
        >
          <RefreshCw size={14} />
          <span>{statusText}</span>
        </button>
        </HoverTip>

        <HoverTip label={text("Remove account", "删除账号")}><Button type="button" variant="ghost" size="icon-xs" className="text-destructive" aria-label={text("Remove account", "删除账号")}
          onClick={remove}>
          <Trash2 size={16} />
        </Button></HoverTip>
      </div>

      {account.kind === "api_key" && !renaming && (
        <div className={`${styles.acctKey} flex items-center gap-[6px] min-w-0`}>
          {editingKey ? (
            <>
              <Input className="font-mono" type="password" autoFocus
                value={replacement} autoComplete="new-password"
                placeholder={text("Paste a new API key", "粘贴新的 API 密钥")}
                onChange={(e) => setReplacement(e.target.value)} disabled={busy} />
              <Button onClick={update} disabled={busy || !replacement.trim()}>{text("Save", "保存")}</Button>
              <HoverTip label={text("Cancel", "取消")}><Button type="button" variant="ghost" size="icon-xs"
                aria-label={text("Cancel replacing API key", "取消替换 API 密钥")} onClick={cancelEdit}>
                <X size={14} />
              </Button></HoverTip>
            </>
          ) : (
            <>
              <Input className="font-mono" readOnly
                value={account.has_value ? account.masked_key : ""}
                placeholder={text("Not set", "未设置")} />
              <HoverTip label={text("Replace API key", "替换 API 密钥")}><Button type="button" variant="ghost" size="icon-xs"
                aria-label={text("Replace API key", "替换 API 密钥")} onClick={startEdit}>
                <KeyRound size={16} />
              </Button></HoverTip>
            </>
          )}
        </div>
      )}

      {rotation
        ? <AccountUseToggle active={account.enabled ?? true} rotation onActivate={() => setEnabled(true)} onDeactivate={() => setEnabled(false)} />
        : <AccountUseToggle active={account.is_active} fixed={account.is_active && account.is_fallback} rotation={false} onActivate={activate} onDeactivate={deactivate} />}
    </Reorder.Item>
  );
}

export function AccountManager({ provider, onChanged }: { provider: Provider; onChanged?: () => void }) {
  const { text } = useTranslation();
  const pid = provider.id;
  const base = `/api/providers/${encodeURIComponent(pid)}/accounts`;

  const [state, setState] = useState<State | null>(null);
  const [newKey, setNewKey] = useState("");
  const [newKeyName, setNewKeyName] = useState("");
  const [newName, setNewName] = useState("");
  const [addingKey, setAddingKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  // Local drag order (account ids). Driven by framer Reorder for instant,
  // FLIP-animated reordering; persisted to /reorder on drag end. orderRef
  // mirrors it so the drag-end commit reads the freshest order (state may
  // not have flushed by the time onDragEnd fires).
  const [order, setOrder] = useState<string[]>([]);
  const orderRef = useRef<string[]>([]);

  const load = useCallback(async () => {
    try {
      const r = await fetch(base);
      if (!r.ok) throw new Error(String(r.status));
      setState((await r.json()) as State);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    }
  }, [base]);

  useEffect(() => { load(); }, [load]);

  // Mirror the server account order into local order, but only when the SET
  // of accounts changes (add / remove). A pure reorder leaves the set equal,
  // so we keep the local order we already applied — no fight with the drag.
  useEffect(() => {
    const ids = (state?.accounts || []).map((a) => a.id);
    setOrder((prev) => {
      const sameSet = prev.length === ids.length
        && prev.every((id) => ids.includes(id)) && ids.every((id) => prev.includes(id));
      const next = sameSet ? prev : ids;
      orderRef.current = next;
      return next;
    });
  }, [state?.accounts]);

  function onReorder(next: ProviderAccountView[]) {
    const ids = next.map((a) => a.id);
    orderRef.current = ids;
    setOrder(ids);
  }
  async function commitOrder() {
    const ids = orderRef.current;
    if (ids.length < 2) return;
    await postAccounts(`${base}/reorder`, { order: ids }, text);
  }

  async function addKey() {
    const key = newKey.trim();
    if (!key) return;
    setBusy(true); setMsg(text("Validating…", "验证中…"));
    // A rejected key answers 4xx with {error}; only a 2xx {ok:true} stored it.
    const r = await fetch(`${base}/keys`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ name: newKeyName.trim(), api_key: key, validate: true }) });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (r.ok && d.ok) { setNewKey(""); setNewKeyName(""); setAddingKey(false); setMsg(""); await load(); onChanged?.(); }
    else setMsg(d.error || text("Could not add the key.", "添加失败。"));
  }
  function toggleAddingKey() {
    if (addingKey) {
      setNewKey("");
      setNewKeyName("");
    }
    setAddingKey((open) => !open);
    setMsg("");
  }
  async function toggleRotation(enabled: boolean) {
    await postAccounts(`${base}/rotation`, { enabled, strategy: state?.strategy }, text);
    await load();
  }
  async function setStrategy(strategy: string) {
    await postAccounts(`${base}/rotation`, { enabled: true, strategy }, text);
    await load();
  }

  if (!state) {
    if (!loadFailed) return null;
    return (
      <div className="flex items-center justify-between gap-[10px]">
        <span className={styles.modelCountSummary}>{text("Could not load the accounts.", "无法加载账号。")}</span>
        <Button variant="elevated" onClick={() => { void load(); }}>{text("Retry", "重试")}</Button>
      </div>
    );
  }
  const accounts = state.accounts || [];
  const multi = accounts.length > 1;
  // Render in local drag order; fall back to server order until the order
  // state has synced (or if it ever drifts out of sync with the account set).
  const byId = new Map(accounts.map((a) => [a.id, a] as const));
  const ordered = order.map((id) => byId.get(id)).filter(Boolean) as ProviderAccountView[];
  const items = ordered.length === accounts.length ? ordered : accounts;

  return (
    <div className="flex flex-col gap-[10px]">
      <div className={styles.detailSectionTitle}>
        <span>{state.add_mode === "api_key" ? text("API keys", "API 密钥") : text(`${provider.label} accounts`, `${provider.label} 账号`)}</span>
        <span className={styles.modelCountSummary}>
          {text(`${accounts.length} ${accounts.length === 1 ? "account" : "accounts"}`, `${accounts.length} 个账号`)}
        </span>
      </div>

      {/* rotation toggle (≥2 accounts) */}
      {multi && (
        <div className={`${styles.detailRow} flex gap-[10px] items-center`} style={{ alignItems: "center" }}>
          <Switch checked={state.rotation} onCheckedChange={toggleRotation} />
          <span style={{ fontSize: "var(--fs-2xs)", flex: 1 }}>{text("Rotate across accounts automatically", "在多个账号之间自动轮询")}</span>
          {state.rotation && (
            <SimpleSelect
              aria-label={text("Rotation strategy", "轮换策略")}
              value={state.strategy}
              onValueChange={setStrategy}
              options={[
                { value: "fill_first", label: text("in order (failover)", "按顺序（容错）") },
                { value: "round_robin", label: text("spread evenly", "均匀轮询") },
                { value: "random", label: text("random", "随机") },
                { value: "least_used", label: text("least used", "最少使用") },
              ]}
            />
          )}
        </div>
      )}

      <Reorder.Group axis="y" values={items} onReorder={onReorder}
        className={styles.accountList}>
        {items.map((a) => (
          <AccountRow key={a.id} provider={pid} account={a} multi={multi}
            rotation={state.rotation} onChanged={onChanged} refresh={load} onCommit={commitOrder} />
        ))}
      </Reorder.Group>

      {/* Keep adding visually secondary once an account exists. */}
      {state.add_mode === "api_key" && (
        <>
          {accounts.length > 0 && (
            <Button type="button" variant="elevated" className="w-full"
              aria-expanded={addingKey} aria-controls="add-api-key-form"
              onClick={toggleAddingKey}>
              {addingKey ? <X size={16} /> : <Plus size={16} />}
              <span>{addingKey ? text("Cancel adding key", "取消添加密钥") : text("Add API key", "添加 API 密钥")}</span>
            </Button>
          )}
          {(accounts.length === 0 || addingKey) && (
            <div id="add-api-key-form" className={styles.addCredentialCard}>
              <div className={styles.addCredentialTitle}>
                {accounts.length === 0 ? text("Add your API key", "添加 API 密钥") : text("New API key", "新 API 密钥")}
              </div>
              <div className={`${styles.addCredentialFields} ${accounts.length === 0 ? styles.addCredentialFieldsSingle : ""}`}>
                {accounts.length > 0 && (
                  <Input  placeholder={text("Account name (optional)", "账号名称（可选）")}
                    value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} disabled={busy} />
                )}
                <Input className="font-mono" type="password" placeholder={text("Paste API key", "粘贴 API 密钥")}
                  value={newKey} onChange={(e) => setNewKey(e.target.value)} disabled={busy} />
                <Button onClick={addKey} disabled={busy || !newKey.trim()}>
                  {busy ? text("Adding…", "添加中…") : text("Add key", "添加密钥")}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
      {/* Providers may advertise additional supported login methods. */}
      {state.add_mode === "api_key" && (provider.login_methods?.length ?? 0) > 0 && (
        <ProviderLogin provider={provider} accountLabel={newName.trim() || undefined} bare
          leadingInput={<Input className="flex-1" placeholder={text("name (optional)", "名字（可选）")} value={newName} onChange={(e) => setNewName(e.target.value)} />}
          onChanged={() => { setNewName(""); load(); onChanged?.(); }} />
      )}
      {state.add_mode === "login" && (
        <ProviderLogin provider={provider} accountLabel={newName.trim() || undefined} bare
          leadingInput={<Input className="flex-1" placeholder={text("name (optional)", "名字（可选）")} value={newName} onChange={(e) => setNewName(e.target.value)} />}
          onChanged={() => { setNewName(""); load(); }} />
      )}
      <div className={styles.accountHelp}>
        {state.add_mode === "api_key"
          ? text("Each key is a separate account. Saved values stay masked.", "每个密钥都是独立账号，保存后的值始终显示为掩码。")
          : text("Sign in to add an account, then enable it for requests.", "登录后添加账号，启用后用于模型请求。")}
      </div>

      {msg && <div style={{ fontSize: "var(--fs-2xs)", opacity: 0.75, marginTop: "0.2rem" }}>{msg}</div>}
    </div>
  );
}
