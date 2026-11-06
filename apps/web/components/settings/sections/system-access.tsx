"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import styles from "../settings-page.module.css";
import { managePageStyles as shared } from "@/components/ui/manage-page";

type Capability = {
  id: string;
  label?: string;
  label_zh?: string;
  status: string;
  detail?: string;
  instruction?: string;
  can_request?: boolean;
  can_open_settings?: boolean;
  settings_available?: boolean;
  settings_pane?: string;
  request_mode?: string;
  setup_group?: string;
  category?: string;
  required?: boolean;
  required_for?: string[];
  target?: string;
  operations?: string[];
  subject?: string;
};
type Report = {
  application?: string;
  platform: string;
  host: string;
  executable: string;
  capabilities: Capability[];
};

const legacyLabels: Record<string, [string, string]> = {
  screen_recording: ["Screen recording", "屏幕录制"],
  accessibility: ["Desktop control", "桌面控制"],
};

function fallbackLabel(id: string, text: (en: string, zh: string) => string) {
  const known = legacyLabels[id];
  if (known) return text(...known);
  return id.replace(/[_-]+/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function groupLabel(id: string, text: (en: string, zh: string) => string) {
  const names: Record<string, [string, string]> = {
    desktop: ["Desktop", "桌面"],
    privacy: ["Privacy", "隐私"],
    media: ["Media", "媒体"],
    files: ["Files", "文件"],
    automation: ["Automation", "自动化"],
    integrations: ["Integrations", "集成"],
    storage: ["Storage", "存储"],
  };
  return names[id] ? text(...names[id]) : id;
}

/** Live executor status; reading this report never opens a permission prompt. */
export function SystemAccess() {
  const { text } = useTranslation();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let generation = 0;
    const controller = new AbortController();
    const check = async () => {
      const current = ++generation;
      try {
        const response = await fetch("/api/system/access", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(String(response.status));
        const data = await response.json();
        if (current === generation) { setReport(data); setError(""); }
      } catch {
        if (!controller.signal.aborted && current === generation) setError(text("Could not check system access.", "无法检查系统权限。"));
      }
    };
    const visible = () => { if (document.visibilityState === "visible") void check(); };
    void check();
    window.addEventListener("focus", visible);
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("openprogram-system-access-changed", visible);
    return () => {
      controller.abort();
      window.removeEventListener("focus", visible);
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("openprogram-system-access-changed", visible);
    };
  }, [text]);

  const local = typeof window !== "undefined" && ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  async function request(row: Capability, openSettings = false) {
    setPending(row.id); setError(""); setNotice("");
    try {
      const response = await fetch(`/api/system/access/${encodeURIComponent(row.id)}?open_settings=${openSettings ? "true" : "false"}`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || String(response.status));
      setNotice(result.status === "granted" ? text("Access confirmed.", "已确认授权。") : openSettings ? text("System Settings opened.", "已打开系统设置。") : text("Authorization request finished without confirmation.", "授权请求结束，但尚未确认授权。"));
      window.dispatchEvent(new Event("openprogram-system-access-changed"));
    } catch (e) { setError(e instanceof Error ? e.message : text("Permission request failed.", "申请权限失败。")); }
    finally { setPending(""); }
  }
  async function setupAll() {
    setPending("all"); setError(""); setNotice("");
    try {
      const response = await fetch("/api/system/access/setup", { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || String(response.status));
      setReport(previous => previous ? { ...previous, capabilities: result.capabilities || previous.capabilities } : previous);
      setNotice(result.status === "granted"
        ? text("All registered native access is confirmed.", "已确认所有已登记的本机权限。")
        : text("Setup finished; review the remaining capabilities below.", "初始化完成，请检查下方仍未授权的权限。"));
      window.dispatchEvent(new Event("openprogram-system-access-changed"));
    } catch (e) { setError(e instanceof Error ? e.message : text("Permission setup failed.", "权限初始化失败。")); }
    finally { setPending(""); }
  }

  const labels: Record<string, string> = {
    granted: text("Granted", "已授权"), not_granted: text("Not authorized", "未授权"),
    unknown: text("Not verified", "未确认"), unavailable: text("Unavailable", "不可用"),
    unsupported: text("Unsupported", "暂不支持"), requesting: text("Requesting", "申请中"),
  };
  const groups = useMemo(() => {
    const result = new Map<string, Capability[]>();
    for (const row of report?.capabilities || []) {
      const group = row.setup_group || row.category || "other";
      const rows = result.get(group) || [];
      rows.push(row); result.set(group, rows);
    }
    return [...result.entries()];
  }, [report]);

  return <section>
    <h3 className={styles.sectionTitle}>{text("System access", "系统权限")}</h3>
    <p className={styles.pageMeta}>{text("Capabilities are read from the execution host registry. Checking status never opens a prompt; use an action on a row to request or open settings.", "权限能力由执行主机的统一注册表提供。检查状态不会弹出授权窗口；只有点击具体行的操作才会申请授权或打开设置。")}</p>
    {!report && !error && <p role="status">{text("Checking…", "正在检查…")}</p>}
    {report && <>
      {report.platform === "Darwin" && local && report.capabilities.some(row => row.status !== "granted" && row.request_mode === "native") &&
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          <Button variant="elevated" disabled={!!pending} onClick={() => void setupAll()}>
            {pending === "all" ? text("Setting up…", "正在初始化…") : text("Set up all OpenProgram access", "初始化全部 OpenProgram 权限")}
          </Button>
        </div>}
      {groups.map(([group, rows]) => <div className={styles.card} key={group}>
        <h4 className={styles.accessGroupTitle}>{groupLabel(group, text)}</h4>
        {rows.map(row => {
          const status = labels[row.status] || row.status;
          const canSettings = (row.settings_available === undefined ? row.can_open_settings !== false : row.settings_available === true) && row.status !== "unsupported" && row.status !== "unavailable";
          const canRequest = row.can_request === true && row.status === "not_granted" && row.request_mode !== "settings";
          return <div className={`${styles.row} ${styles.rowTop}`} key={row.id}>
            <div className={styles.label}>
              <div className="flex flex-wrap items-center gap-[8px]">
                {text(row.label || fallbackLabel(row.id, text), row.label_zh || fallbackLabel(row.id, text))}
                <span className={`${shared.badge} ${row.status === "granted" ? shared.badgeGreen : row.status === "not_granted" ? shared.badgeYellow : ""}`}>{status}</span>
              </div>
              <p className={styles.rowHelp}>{row.detail || (row.status === "granted" ? text("The execution program has this access.", "当前执行程序已获得授权。") : row.status === "not_granted" ? text("This access has not been granted to the execution program.", "当前执行程序尚未获得这项系统授权。") : row.status === "unknown" ? text("The host cannot verify this access yet.", "当前主机尚不能确认这项权限。") : row.status === "unsupported" ? text("This capability is not supported by the current host.", "当前主机暂不支持这项能力。") : text("This capability is unavailable in the current environment.", "当前环境无法提供这项能力。"))}</p>
              {row.instruction && row.status !== "granted" && <p className={styles.rowHelp}>{row.instruction}</p>}
              {(row.required || row.required_for?.length) && <p className={styles.rowHelp}>{text("Used by: ", "使用于：")}{(row.required_for || []).join(", ")}</p>}
              {row.operations?.length ? <p className={styles.rowHelp}>{text("Operations: ", "操作：")}{row.operations.join(", ")}</p> : null}
            </div>
            {report.platform === "Darwin" && local && row.status !== "granted" && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {canRequest && <Button variant="elevated" disabled={!!pending} onClick={() => void request(row)}>{pending === row.id ? text("Requesting…", "正在申请…") : text("Request authorization", "请求授权")}</Button>}
              {canSettings && <Button variant="ghost" disabled={!!pending} onClick={() => void request(row, true)}>{text("Open System Settings", "打开系统设置")}</Button>}
            </div>}
          </div>;
        })}
      </div>)}
      <div className={styles.card}>
        <div className={`${styles.row} ${styles.rowTop}`}>
          <div className={styles.label}>
            <div>{text("Execution host", "执行主机")}</div>
            <p className={styles.rowHelp}>{report.application ? `${report.application} · ` : ""}{report.host} · {report.platform}</p>
            <details className={styles.accessDetails}><summary>{text("Execution process", "执行程序")}</summary><code>{report.executable}</code></details>
          </div>
        </div>
      </div>
    </>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
