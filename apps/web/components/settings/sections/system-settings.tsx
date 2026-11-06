"use client";

/**
 * System settings — schema-driven editor, styled to match the other
 * settings tabs (same .section/.row/.label/.control from settings-page.module
 * .css). Renders the SAME settings the TUI panel and `openprogram config`
 * edit, fetched from /api/settings (backed by openprogram.state.settings).
 * One SettingSpec server-side → one row here. See docs/design/cli/redesign.md.
 */
import { useEffect, useState } from "react";

import { SystemAccess } from "./system-access";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { SimpleSelect } from "@/components/ui/select";
import { useTranslation } from "@/lib/i18n";
import styles from "../settings-page.module.css";

interface Row {
  key: string;
  group: string;
  label: string;
  widget: "number" | "toggle" | "enum" | "status" | "text" | "json";
  apply: "live" | "next_start";
  help?: string;
  value?: unknown;
  choices?: string[];
  set?: boolean;
}

// On the web, only show settings that have NO dedicated page. Providers,
// Search, Memory, and Tools already have their own surfaces (the Providers,
// Search, and Memory settings tabs), so re-listing them here would just
// duplicate them. The schema still feeds all of them on the TUI (which has
// no settings pages) and the CLI — this is purely which groups the web
// chooses to render. Ports and the model fallback chain have no other page.
const WEB_GROUPS = ["Models", "Ports"];

export function SystemSettings() {
  const { t, text } = useTranslation();
  const [rows, setRows] = useState<Row[]>([]);
  const [status, setStatus] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((d) => setRows((d.settings || []).filter((r: Row) => WEB_GROUPS.includes(r.group))))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  async function save(key: string, value: unknown) {
    let res: { applied?: string; value?: unknown; note?: string; error?: string };
    try {
      res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value }),
      }).then((r) => r.json());
    } catch (e) {
      res = { error: String(e) };
    }
    if (res.error) {
      setStatus((s) => ({ ...s, [key]: `✗ ${res.error}` }));
      return;
    }
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, value: res.value } : r)));
    const when = res.applied === "next_start"
      ? text("Saved · takes effect on next start", "已保存 · 下次启动后生效")
      : text("Saved", "已保存");
    setStatus((s) => ({ ...s, [key]: `✓ ${when}${res.note ? ` · ${res.note}` : ""}` }));
  }

  const groups: string[] = [];
  rows.forEach((r) => {
    if (!groups.includes(r.group)) groups.push(r.group);
  });

  // The header stays put while rows load, like the Memory page, so the
  // title does not pop in after the body.
  const pageHeader = (
    <div className={styles.pageHeader}>
      <h2 className={styles.pageTitle}>{t("settings.tab.system")}</h2>
      <p className={styles.pageMeta}>
        {text(
          "Settings with no dedicated page. Some take effect on the next start.",
          "没有独立页面的设置。部分项会在下次启动后生效。",
        )}
      </p>
    </div>
  );

  if (!loaded) {
    return (
      <div className={styles.page}>
        {pageHeader}
        <div className={styles.pageBody}>
          <div className={styles.rowHelp}>{text("Loading…", "加载中…")}</div>
        </div>
      </div>
    );
  }

  // Same shell as GeneralSection: .page > .pageHeader > .pageBody, then a
  // <section> per group with its .sectionTitle + a .card wrapping the rows.
  return (
    <div className={styles.page}>
      {pageHeader}
      <div className={styles.pageBody}>
        <SystemAccess />
        {groups.map((g) => (
          <section key={g}>
            <h3 className={styles.sectionTitle}>{g}</h3>
            <div className={styles.card}>
              {rows
                .filter((r) => r.group === g)
                .map((r) => {
                  const st = status[r.key];
                  return (
                    <div className={`${styles.row} ${styles.rowTop} ${styles.systemRow}`} key={r.key}>
                      <div className={styles.label}>
                        <div>{r.label}</div>
                        {r.help ? (
                          <div className={styles.rowHelp}>{r.help}</div>
                        ) : null}
                        {st ? (
                          <div className={st.startsWith("✗") ? styles.rowStatusError : styles.rowStatusOk}>
                            {st}
                          </div>
                        ) : r.apply === "next_start" ? (
                          <div className={styles.rowStatus}>
                            {text("Takes effect on next start", "下次启动后生效")}
                          </div>
                        ) : null}
                      </div>
                      <div className={styles.control}>
                        <Control row={r} onSave={save} />
                      </div>
                    </div>
                  );
                })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function Control({ row, onSave }: { row: Row; onSave: (k: string, v: unknown) => void }) {
  const { text } = useTranslation();
  if (row.widget === "status") {
    const ok = !!row.value;
    return (
      <span className={ok ? styles.rowStatusOk : styles.rowStatus}>
        {ok ? `✓ ${text("Configured", "已配置")}` : `✗ ${text("Not configured", "未配置")}`}
      </span>
    );
  }
  if (row.widget === "toggle") {
    return (
      <Switch
        checked={!!row.value}
        onCheckedChange={(v) => onSave(row.key, v)}
      />
    );
  }
  if (row.widget === "enum") {
    return (
      <SimpleSelect
        label={row.label}
        value={String(row.value)}
        onValueChange={(value) => onSave(row.key, value)}
        options={(row.choices || []).map((c) => ({ value: c, label: c }))}
      />
    );
  }
  // Plain text input — a port number is typed, not nudged one at a time,
  // so no <input type="number"> spinner arrows; numbers get the numeric
  // keyboard. Text and JSON values (bind address, allowed origins) get a
  // wider, left-aligned field. The backend validates and reports inline.
  const isNumber = row.widget === "number";
  const initial = typeof row.value === "object" && row.value !== null
    ? JSON.stringify(row.value)
    : String(row.value ?? "");
  return (
    <Input
      type="text"
      inputMode={isNumber ? "numeric" : undefined}
      spellCheck={false}
      data-kind={isNumber ? "number" : "text"}
      defaultValue={initial}
      className={isNumber ? "w-[120px] text-right" : "w-[min(320px,100%)] text-left font-mono"}
      onBlur={(e) => {
        if (e.target.value !== initial) onSave(row.key, e.target.value);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
      }}
    />
  );
}
