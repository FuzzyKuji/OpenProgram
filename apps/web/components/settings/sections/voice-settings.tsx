"use client";

/**
 * Voice — which speech-to-text engine the composer microphone uses.
 *
 * Engine, language and model are the `voice.*` settings (state.settings);
 * the status card shows what `auto` resolves to and which engines work
 * on this computer (/api/voice/status). The microphone itself has no
 * options of its own: everything about it is set here.
 */
import { useCallback, useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { useTranslation } from "@/lib/i18n";
import { SPOKEN_LANGUAGES, type SpokenLanguage } from "@/lib/voice/spoken-languages";
import { SettingsDropdown, type DropdownOption } from "./general-section";
import styles from "../settings-page.module.css";

type Engine = "auto" | "openai" | "groq" | "local";
type Language = "auto" | SpokenLanguage;

interface EngineRow {
  id: Exclude<Engine, "auto">;
  available: boolean;
  detail: string;
}

interface VoiceStatus {
  engine: Engine;
  language: Language;
  model: string;
  resolved_engine: Exclude<Engine, "auto"> | null;
  resolved_model: string;
  engines: EngineRow[];
  default_models: Record<Exclude<Engine, "auto">, string>;
}

export function VoiceSettings() {
  const { text } = useTranslation();
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [model, setModel] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/voice/status");
      if (!response.ok) throw new Error(String(response.status));
      const next: VoiceStatus = await response.json();
      setStatus(next);
      setModel(next.model);
    } catch (error) {
      setMessage(text(`Could not load voice settings: ${error}`, `无法加载语音设置：${error}`));
    }
  }, [text]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(key: string, value: string) {
    setMessage("");
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value }),
      });
      const result = await response.json();
      if (!response.ok || result.error) throw new Error(result.error || String(response.status));
      await load();
    } catch (error) {
      setMessage(text(`Save failed: ${error}`, `保存失败：${error}`));
    }
  }

  const engineName = (id: Engine) => ({
    auto: text("Auto", "自动"),
    openai: "OpenAI",
    groq: "Groq",
    local: text("Local whisper.cpp", "本机 whisper.cpp"),
  })[id];

  const engineOptions: DropdownOption<Engine>[] = (["auto", "openai", "groq", "local"] as Engine[])
    .map((id) => ({ value: id, label: engineName(id) }));
  const languageOptions: DropdownOption<Language>[] = [
    { value: "auto", label: text("Detect automatically", "自动识别") },
    ...SPOKEN_LANGUAGES.map(({ code, name }) => ({ value: code, label: name })),
  ];

  const detail = (row: EngineRow) => {
    if (row.id === "local") {
      if (!row.available) return text("whisper.cpp is not installed — run `brew install whisper-cpp`.", "未安装 whisper.cpp，运行 `brew install whisper-cpp` 安装。");
      return row.detail === "model ready"
        ? text("Installed, model downloaded.", "已安装，模型已下载。")
        : text("Installed; the model downloads on first use.", "已安装，第一次使用时下载模型。");
    }
    return row.available
      ? text("API key set.", "已设置 API key。")
      : text("No API key — add one in Settings → Providers.", "没有 API key，请在 设置 → 模型服务 里添加。");
  };

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h2 className={styles.pageTitle}>{text("Voice", "语音")}</h2>
        <p className={styles.pageMeta}>
          {text(
            "Speak into the microphone in the bottom-left corner of the input box, or hold ⌥Space while typing. Each phrase is transcribed when you pause and lands in the box for you to edit and send.",
            "点输入框左下角的麦克风说话，或在输入时按住 ⌥空格。每说完一句停顿一下就会转写，文字落进输入框，改完再发。",
          )}
        </p>
      </div>
      <div className={styles.pageBody}>
        <section>
          <h3 className={styles.sectionTitle}>{text("Speech to text", "语音转文字")}</h3>
          <div className={styles.card}>
            <div className={styles.row}>
              <div className={styles.label}>
                {text("Engine", "识别服务")}
                <div className={styles.rowHelp}>
                  {status?.resolved_engine
                    ? text(
                      `In use: ${engineName(status.resolved_engine)} · ${status.resolved_model}`,
                      `当前使用：${engineName(status.resolved_engine)} · ${status.resolved_model}`,
                    )
                    : text("No engine is usable yet.", "还没有可用的识别服务。")}
                </div>
              </div>
              <div className={styles.control}>
                {status ? (
                  <SettingsDropdown
                    label={text("Engine", "识别服务")}
                    value={status.engine}
                    options={engineOptions}
                    onChange={(value) => void save("voice.engine", value)}
                  />
                ) : null}
              </div>
            </div>
            <div className={styles.row}>
              <div className={styles.label}>{text("Spoken language", "说话语言")}</div>
              <div className={styles.control}>
                {status ? (
                  <SettingsDropdown
                    label={text("Spoken language", "说话语言")}
                    value={status.language}
                    options={languageOptions}
                    onChange={(value) => void save("voice.language", value)}
                  />
                ) : null}
              </div>
            </div>
            {status && status.engine !== "auto" ? (
              <div className={styles.row}>
                <div className={styles.label}>
                  {text("Model", "模型")}
                  <div className={styles.rowHelp}>
                    {text(
                      `Empty uses ${status.default_models[status.engine]}.`,
                      `留空使用 ${status.default_models[status.engine]}。`,
                    )}
                  </div>
                </div>
                <div className={styles.control}>
                  <Input
                    className={styles.authMono}
                    spellCheck={false}
                    placeholder={status.default_models[status.engine]}
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    onBlur={() => {
                      if (model.trim() !== status.model) void save("voice.model", model.trim());
                    }}
                  />
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section>
          <h3 className={styles.sectionTitle}>{text("Engines on this computer", "这台电脑上的识别服务")}</h3>
          <div className={styles.card}>
            {(status?.engines ?? []).map((row) => (
              <div key={row.id} className={styles.row}>
                <div className={styles.label}>
                  {engineName(row.id)}
                  <div className={row.available ? styles.rowStatusOk : styles.rowHelp}>{detail(row)}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {message ? <p className={styles.rowStatusError}>{message}</p> : null}
      </div>
    </div>
  );
}
