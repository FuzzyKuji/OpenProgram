"use client";

/** General settings — theme, font, language, app metadata. */
import { useEffect, useId, useState, type CSSProperties } from "react";

import { useTranslation, type Locale } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { SolarIcon } from "@/components/solar-icons";
import { Switch } from "@/components/ui/switch";
import {
  desktopBridge,
  type DesktopBridge,
  type DesktopUpdateState,
} from "@/lib/desktop/desktop-bridge";
import { useChatWidthPref, useFontPref, useTabularNumsPref, FONT_LABELS, fontStack, type FontKey } from "@/lib/prefs/appearance/font-pref";
import { setUserProfile, useUserProfile, type UserProfilePrefs } from "@/lib/prefs/user-profile";
import {
  Avatar,
  AvatarPicker,
  type AvatarConfig,
} from "@/components/avatar";
import {
  useThemePref,
  ACCENT_PRESETS,
  CUSTOM_CSS_TEMPLATE,
  DEFAULT_TABROW_COLOR,
  TABROW_COLOR_PRESETS,
  THEME_MODES,
  THEME_STYLES,
  THEME_STYLE_PAIRS,
  type ThemeMode,
  type ThemeStyle,
} from "@/lib/prefs/appearance/theme-pref";
import { useVisualEffectsPref } from "@/lib/prefs/appearance/visual-effects-pref";
import { CODE_RAIN_DENSITY, useWelcomeBackdropPref, type BackdropTheme } from "@/lib/prefs/appearance/welcome-backdrop-pref";
import { DRAG_SURFACE_STYLE, VISUAL_EFFECTS_LIMITS, type VisualEffectKey } from "@/lib/prefs/appearance/visual-effects-config";
import styles from "../settings-page.module.css";
import { DesktopAttentionSection } from "./desktop-attention-section";
import { SimpleSelect } from "@/components/ui/select";
import { setDefaultTranscriptView, useDefaultTranscriptView } from "@/lib/prefs/transcript-view";
import { setComposerPredictions, useComposerPredictions } from "@/lib/prefs/composer-predictions";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Slider } from "@/components/ui/slider";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { SettingsPage, SettingsRow, SettingsSection } from "../settings-ui";

const FONT_OPTIONS: FontKey[] = ["system", "inter", "serif", "mono"];

export type DropdownOption<T extends string> = {
  value: T;
  label: string;
  style?: CSSProperties;
};

export function SettingsDropdown<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: DropdownOption<T>[];
  onChange: (v: T) => void;
  /** Name of the setting this dropdown controls. The visible row label
   *  is a plain <div>, so it can't be associated with htmlFor — pass the
   *  same string here and the trigger announces "Font, Inter" instead of
   *  a bare value. */
  label?: string;
}) {
  return (
    <SimpleSelect
      value={value}
      onValueChange={onChange}
      aria-label={label}
      options={options.map((option) => ({
        value: option.value,
        label: option.style ? <span style={option.style}>{option.label}</span> : option.label,
      }))}
    />
  );
}

const FONT_SELECT_OPTIONS: DropdownOption<FontKey>[] = FONT_OPTIONS.map((font) => ({
  value: font,
  label: FONT_LABELS[font],
  style: { fontFamily: fontStack(font) },
}));

const LANG_OPTIONS: DropdownOption<Locale>[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
];

/** Letter-avatar background swatches. */
const PROFILE_COLORS = [
  "#4f8ef7", "#5aad4e", "#d4843a", "#9d6fe0", "#e0445a", "#2db3d5",
  "#e0b020", "#35b89a", "#e066b3", "#6b8dd6", "#8fbf3f", "#d9694f",
  "#52c4c4", "#b08be0", "#c79a4a", "#e08a3a", "#6fae6f", "#d05fa0",
];

/** The local user's name and avatar, shown at the bottom of the sidebar. */
function UserSection() {
  const { t } = useTranslation();
  const profile = useUserProfile();
  const nameId = useId();

  function update(next: Partial<UserProfilePrefs>) {
    setUserProfile({ ...profile, ...next });
  }
  function updateInitial(raw: string) {
    const cleaned = raw.trim();
    const initial =
      cleaned.length === 0
        ? Array.from(profile.name.trim())[0]?.toUpperCase() ?? "?"
        : Array.from(cleaned)[0]!.toUpperCase();
    update({ initial });
  }

  return (
    <SettingsSection title={t("general.section.you")}>
      <SettingsRow label={t("general.profile.preview")}>
        <span className="inline-flex items-center gap-2.5">
          <Avatar
            size={40}
            name={profile.name}
            config={
              profile.avatar?.kind === "letter"
                ? {
                    kind: "letter",
                    letter: profile.initial,
                    bg: profile.color,
                  }
                : profile.avatar
            }
          />
          <span className="font-medium">{profile.name}</span>
        </span>
      </SettingsRow>
      <SettingsRow label={t("general.profile.name")} htmlFor={nameId}>
        <Input
          id={nameId}
          className="w-48"
          value={profile.name}
          maxLength={32}
          placeholder={t("general.you.name.placeholder")}
          onChange={(e) => update({ name: e.target.value.slice(0, 32) })}
        />
      </SettingsRow>
      <SettingsRow label={t("general.avatar")} stacked>
        <AvatarPicker
          value={profile.avatar}
          onChange={(avatar: AvatarConfig) => update({ avatar })}
          name={profile.name}
          letterBg={profile.color}
          letterText={profile.initial}
          onLetterBgChange={(color) => update({ color })}
          onLetterTextChange={updateInitial}
          colors={PROFILE_COLORS}
        />
      </SettingsRow>
    </SettingsSection>
  );
}

export function ApplicationSection() {
  const { t, text } = useTranslation();
  const [updateState, setUpdateState] = useState<DesktopUpdateState | null>(null);
  const [hostVersion, setHostVersion] = useState("unknown");
  const [rawInstallType, setInstallType] = useState("unknown");
  // The backend reports an enum (openprogram/updater/detect.py); show words.
  const installType = rawInstallType === "source_checkout"
    ? text("Source checkout", "源码检出")
    : rawInstallType === "managed_release"
      ? text("Managed release", "托管发行版")
      : text("Unknown", "未知");
  const [bridge, setBridge] = useState<DesktopBridge | null>(null);
  const [updateActionError, setUpdateActionError] = useState<string | null>(null);

  useEffect(() => {
    const currentBridge = desktopBridge();
    setBridge(currentBridge);
    const updates = currentBridge?.updates;
    if (updates) {
      let active = true;
      void updates.getState().then((state) => {
        if (active && state) setUpdateState(state);
      }).catch((error: unknown) => {
        if (active) setUpdateActionError(error instanceof Error ? error.message : String(error));
      });
      const unsubscribe = updates.onState((state) => {
        if (active) setUpdateState(state);
      });
      return () => {
        active = false;
        unsubscribe();
      };
    }

    const controller = new AbortController();
    void fetch("/api/system/version", { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("version request failed")))
      .then((payload: { currentVersion?: unknown; installType?: unknown }) => {
        if (typeof payload.currentVersion === "string") setHostVersion(payload.currentVersion);
        if (typeof payload.installType === "string") setInstallType(payload.installType);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const runUpdateAction = async (action: () => Promise<DesktopUpdateState | null | void>) => {
    setUpdateActionError(null);
    try {
      const state = await action();
      if (state) setUpdateState(state);
    } catch (error) {
      setUpdateActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const failedStatusText = text("Update check failed", "更新检查失败");
  const statusDetail = updateActionError
    || (updateState?.status === "error" ? updateState.error : null)
    || undefined;
  const statusText = (() => {
    if (updateActionError) return failedStatusText;
    switch (updateState?.status) {
      case "checking": return text("Checking…", "正在检查…");
      case "up-to-date": return text("Up to date", "已是最新版本");
      case "available": return text(`OpenProgram ${updateState.release?.latestVersion} is available`, `OpenProgram ${updateState.release?.latestVersion} 可用`);
      case "downloading": {
        const progress = updateState.progress;
        const percentage = progress?.total ? Math.floor(progress.downloaded / progress.total * 100) : 0;
        const downloaded = progress?.downloaded.toLocaleString() || "0";
        const total = progress?.total.toLocaleString() || "0";
        return text(
          `Downloading… ${downloaded} / ${total} bytes (${percentage}%)`,
          `正在下载… ${downloaded} / ${total} 字节（${percentage}%）`,
        );
      }
      case "downloaded": return text("Installer opened", "安装程序已打开");
      case "error": return failedStatusText;
      default: return text("Not checked", "尚未检查");
    }
  })();

  const busy = updateState?.status === "checking" || updateState?.status === "downloading";
  const progress = updateState?.progress;

  return (
    <SettingsSection title={t("general.section.application")}>
      <SettingsRow label={t("general.version")}>
        <span className="text-fs-base text-text-muted">{updateState?.currentVersion || hostVersion}</span>
      </SettingsRow>
      {bridge?.updates ? (
        <>
          <SettingsRow label={text("Automatically check for updates", "自动检查更新")} htmlFor="automatic-update-checks">
            <Switch
              id="automatic-update-checks"
              checked={updateState?.automaticChecks ?? true}
              onCheckedChange={(checked) => { void runUpdateAction(() => bridge.updates.setAutomaticChecks(checked)); }}
            />
          </SettingsRow>
          <SettingsRow label={text("Update status", "更新状态")}>
            <span
              className="text-fs-base text-text-muted"
              role={updateState?.status === "downloading" ? "progressbar" : "status"}
              aria-live={updateState?.status === "downloading" ? undefined : "polite"}
              aria-atomic="true"
              aria-valuemin={progress ? 0 : undefined}
              aria-valuemax={progress?.total}
              aria-valuenow={progress?.downloaded}
              aria-valuetext={progress ? statusText : undefined}
              data-tip={statusDetail}
            >
              {statusText}
            </span>
          </SettingsRow>
          {updateState?.release?.publishedAt && updateState.release.status === "available" && (
            <SettingsRow label={text("Published", "发布时间")}>
              <span className="text-fs-base text-text-muted">{new Date(updateState.release.publishedAt).toLocaleDateString()}</span>
            </SettingsRow>
          )}
          {updateState?.release?.releaseNotes && updateState.release.status === "available" && (
            <SettingsRow label={text("Release notes", "版本说明")} stacked>
              <p className="text-fs-base whitespace-pre-wrap text-text-muted">
                {updateState.release.releaseNotes.slice(0, 600)}
              </p>
            </SettingsRow>
          )}
          <SettingsRow label={text("Actions", "操作")}>
            <Button variant="elevated" disabled={busy} onClick={() => { void runUpdateAction(() => bridge.updates.check()); }}>
              {text("Check now", "立即检查")}
            </Button>
            {updateState?.release?.status === "available" && (
              <Button disabled={busy} onClick={() => { void runUpdateAction(() => bridge.updates.download()); }}>
                {text("Download and open installer", "下载并打开安装程序")}
              </Button>
            )}
            {updateState?.release && (
              <Button variant="elevated" onClick={() => { void runUpdateAction(() => bridge.updates.openRelease()); }}>
                {text("View release", "查看 Release")}
              </Button>
            )}
          </SettingsRow>
        </>
      ) : (
        <>
          <SettingsRow label={text("Installation", "安装类型")}>
            <span className="text-fs-base text-text-muted">{installType}</span>
          </SettingsRow>
          <SettingsRow label={text("Check for updates", "检查更新")}>
            <div className="grid gap-1 text-right font-mono text-fs-base text-text-muted">
              <code>openprogram upgrade --check</code>
              <code>openprogram upgrade</code>
            </div>
          </SettingsRow>
        </>
      )}
      <SettingsRow label={t("general.framework")}>
        <span className="text-fs-base text-text-muted">Agentic Programming</span>
      </SettingsRow>
    </SettingsSection>
  );
}

export function GeneralSection() {
  const { t, text, locale, setLocale } = useTranslation();
  const { font, setFont } = useFontPref();
  const { tabularNums, setTabularNums } = useTabularNumsPref();
  const { chatWidth, setChatWidth } = useChatWidthPref();
  const transcriptView = useDefaultTranscriptView();
  const predictions = useComposerPredictions();
  const {
    style,
    mode,
    setStyle,
    setMode,
    accent,
    setAccent,
    resetAccent,
    packageAccent,
    tabrowColor,
    setTabrowColor,
    customCss,
    customCssEnabled,
    setCustomCssEnabled,
    setCustomCss,
    insertCustomCssTemplate,
    clearCustomCss,
  } = useThemePref();

  const MODE_LABELS: Record<ThemeMode, string> = {
    auto: text("Auto", "跟随系统"),
    dark: text("Dark", "深色"),
    light: text("Light", "浅色"),
  };

  const STYLE_LABELS: Record<ThemeStyle, string> = {
    beige: text("Beige", "暖色"),
    neutral: text("Neutral", "中性"),
    aurora: text("Aurora", "极光"),
    vivid: text("Vivid", "彩色"),
  };

  const accentValue = accent ?? packageAccent;
  const { effects, setEffect, resetEffects } = useVisualEffectsPref();
  const welcomeBackdrop = useWelcomeBackdropPref();
  const effectControls: { key: VisualEffectKey; label: string; unit: string }[] = [
    { key: "transparency", label: text("Transparency", "透明度"), unit: "%" },
    { key: "blur", label: text("Background blur", "背景模糊"), unit: "px" },
    { key: "shadow", label: text("Shadow strength", "阴影强度"), unit: "%" },
  ];

  return (
    <SettingsPage title={t("general.title")} description={t("general.meta")}>
      <SettingsSection title={t("general.section.preferences")}>
        <SettingsRow label={text("Mode", "明暗模式")} stacked>
          <ThemeChoices
            name="theme-mode"
            value={mode}
            onChange={(value) => setMode(value as ThemeMode)}
            options={THEME_MODES.map((m) => ({
              value: m,
              label: MODE_LABELS[m],
              theme: m === "auto" ? THEME_STYLE_PAIRS[style].dark : THEME_STYLE_PAIRS[style][m],
            }))}
          />
        </SettingsRow>

        <SettingsRow label={text("Color style", "颜色风格")} stacked>
          <ThemeChoices
            name="theme-style"
            value={style}
            onChange={(value) => setStyle(value as ThemeStyle)}
            options={THEME_STYLES.map((s) => ({
              value: s,
              label: STYLE_LABELS[s],
              theme: mode === "auto" ? THEME_STYLE_PAIRS[s].dark : THEME_STYLE_PAIRS[s][mode],
            }))}
          />
        </SettingsRow>

        {style === "vivid" ? (
          <SettingsRow
            label={text("Tab bar color", "标签栏颜色")}
            description={text(
              "Chrome's colour set. Panels, text and the accent take the same hue, unless Accent color below overrides the accent.",
              "Chrome 同款颜色。面板、文字和强调色都跟着用同一色相；下方强调色设了自定义色时，强调色以它为准。",
            )}
            stacked
          >
            <ColorSwatches
              label={text("Tab bar color", "标签栏颜色")}
              customLabel={text("Custom tab bar color", "自定义标签栏颜色")}
              resetLabel={text("Reset", "重置")}
              presets={TABROW_COLOR_PRESETS}
              value={tabrowColor ?? DEFAULT_TABROW_COLOR}
              onPick={setTabrowColor}
              onReset={() => setTabrowColor(null)}
              resetDisabled={!tabrowColor}
            />
          </SettingsRow>
        ) : null}

        <SettingsRow
          label={text("Accent color", "强调色")}
          description={accent
            ? text(
              `Buttons, links and highlights. Your colour ${accent} overrides the ${STYLE_LABELS[style]} style's own accent${style === "vivid" ? ", which follows the tab bar colour" : ""}; Follow theme drops it.`,
              `按钮、链接和高亮。你选的 ${accent} 覆盖了${STYLE_LABELS[style]}风格自己的强调色${style === "vivid" ? "（它跟随标签栏颜色）" : ""}；点"跟随主题"即恢复。`,
            )
            : text(
              `Buttons, links and highlights. Follows the ${STYLE_LABELS[style]} style${style === "vivid" ? " and its tab bar colour" : ""}; picking a colour overrides it.`,
              `按钮、链接和高亮。跟随${STYLE_LABELS[style]}风格${style === "vivid" ? "和它的标签栏颜色" : ""}；选一个颜色即覆盖它。`,
            )}
          stacked
        >
          <ColorSwatches
            label={text("Accent color", "强调色")}
            customLabel={text("Custom accent color", "自定义强调色")}
            resetLabel={text("Follow theme", "跟随主题")}
            presets={ACCENT_PRESETS}
            value={accentValue}
            onPick={setAccent}
            onReset={() => resetAccent()}
            resetDisabled={!accent}
          />
        </SettingsRow>

        <SettingsRow
          label={text("Theme", "主题")}
          description={text(
            "Standard keeps the colour style alone. Code rain gives chats a Matrix look: code rain behind an empty chat, new messages fall in through it, and anything in progress shows as code. Gradient puts an indigo, violet and teal backdrop behind the new tab. Saved on this device.",
            "标准只用上面的颜色风格。代码雨是黑客帝国风格：空白对话背后下代码雨，新消息从雨中落下，进行中的状态都显示为代码。彩色渐变在新标签页背后铺一层靛蓝、紫和青色的渐变。保存在此设备。",
          )}
          stacked
        >
          <RadioGroup
            value={welcomeBackdrop.theme}
            onValueChange={(value) => welcomeBackdrop.setTheme(value as BackdropTheme)}
            className="flex flex-wrap gap-3"
          >
            {([
              ["standard", text("Standard", "标准"), "theme-standard"],
              ["code-rain", text("Code rain", "代码雨"), "welcome-code-rain"],
              ["gradient", text("Gradient", "彩色渐变"), "theme-gradient"],
            ] as const).map(([value, label, id]) => (
              <label key={value} htmlFor={id} className={styles.themeTile}>
                <span
                  className={styles.themeSwatch}
                  data-theme={mode === "auto" ? THEME_STYLE_PAIRS[style].dark : THEME_STYLE_PAIRS[style][mode]}
                  data-scene={value}
                  aria-hidden="true"
                >
                  {value === "code-rain" ? <span className={styles.themeRain}>1 0 1 1</span> : (
                    <>
                      <span className={styles.themeDot} style={{ background: value === "gradient" ? "#fff" : "var(--accent-orange)" }} />
                      <span className={styles.themeDot} style={{ background: value === "gradient" ? "#c4b5fd" : "var(--accent-green)" }} />
                      <span className={styles.themeDot} style={{ background: value === "gradient" ? "#67e8f9" : "var(--text-primary)" }} />
                    </>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  <RadioGroupItem value={value} id={id} />
                  <span className="text-fs-base">{label}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        </SettingsRow>

        {welcomeBackdrop.enabled && (
          <SettingsRow
            label={text("Code rain density", "代码雨密度")}
            description={text(
              "How many streams fall at once. Applies immediately.",
              "同时落下的雨滴有多少。即时生效。",
            )}
            stacked
          >
            <Field>
              <div className="flex items-center justify-between gap-2">
                <FieldLabel htmlFor="welcome-code-rain-density">{text("Density", "密度")}</FieldLabel>
                <span className="text-fs-base text-text-muted">{welcomeBackdrop.density}%</span>
              </div>
              <Slider
                id="welcome-code-rain-density"
                min={CODE_RAIN_DENSITY.min}
                max={CODE_RAIN_DENSITY.max}
                step={5}
                value={[welcomeBackdrop.density]}
                aria-valuetext={`${welcomeBackdrop.density}%`}
                onValueChange={([value]) => welcomeBackdrop.setDensity(value)}
              />
            </Field>
          </SettingsRow>
        )}

        <SettingsRow
          label={text("Tab drag appearance", "标签拖动外观")}
          description={text(
            "Applies immediately to tab dragging inside and outside the strip, and split-pane title previews. 0% transparency is opaque; 0px blur and 0% shadow disable those effects. Saved on this device.",
            "即时应用于标签栏内外的标签拖动预览和分屏标题预览。透明度 0% 为不透明，模糊 0px 和阴影 0% 分别关闭对应效果。保存在此设备。",
          )}
          stacked
        >
          <div className="grid gap-6 sm:grid-cols-[minmax(0,1fr)_14rem]">
            <FieldGroup className="gap-4">
              {effectControls.map(({ key, label, unit }) => (
                <Field key={key}>
                  <div className="flex items-center justify-between gap-2">
                    <FieldLabel htmlFor={`visual-effect-${key}`}>{label}</FieldLabel>
                    <span className="text-fs-base text-text-muted">{effects[key]}{unit}</span>
                  </div>
                  <Slider
                    id={`visual-effect-${key}`}
                    min={VISUAL_EFFECTS_LIMITS[key].min}
                    max={VISUAL_EFFECTS_LIMITS[key].max}
                    step={1}
                    value={[effects[key]]}
                    aria-valuetext={`${effects[key]} ${unit}`}
                    onValueChange={([value]) => setEffect(key, value)}
                  />
                </Field>
              ))}
              <div>
                <Button variant="elevated" onClick={resetEffects}>
                  {text("Restore defaults", "恢复默认")}
                </Button>
              </div>
            </FieldGroup>
            <div className={styles.effectsPreviewBackground} aria-hidden="true">
              <span className={styles.effectsPreviewBackdrop}>Aa 123 • Aa 123</span>
              <div className={styles.effectsPreviewTab} style={DRAG_SURFACE_STYLE}>
                <svg viewBox="0 0 16 16" width="16" height="16" fill="none">
                  <rect x="2" y="2" width="12" height="12" rx="3" stroke="currentColor" />
                  <path d="M2 6h12" stroke="currentColor" />
                </svg>
                <span>{text("Dragged tab", "拖动中的标签")}</span>
              </div>
            </div>
          </div>
        </SettingsRow>

        <SettingsRow
          label={text("Custom CSS", "自定义 CSS")}
          description={text(
            "Overlay on the current theme package. Turn on Enable custom CSS to apply it. Use Insert template for a starter snippet, or Clear to remove it. Applies live, saved in this browser. You can still target any data-theme.",
            "叠加在当前主题包之上。打开「启用自定义 CSS」后生效。可用「插入模板」写入示例，或「清空」删除。即时生效，仅保存在本浏览器。仍可针对任意 data-theme。",
          )}
          stacked
        >
          <div className="flex flex-wrap items-center gap-2">
            <Field orientation="horizontal" className="w-auto">
              <Switch
                id="custom-css-enabled"
                checked={customCssEnabled}
                onCheckedChange={setCustomCssEnabled}
              />
              <FieldLabel htmlFor="custom-css-enabled">{text("Enable custom CSS", "启用自定义 CSS")}</FieldLabel>
            </Field>
            <div className="ms-auto flex gap-2">
              <Button variant="elevated" onClick={() => insertCustomCssTemplate()}>
                {text("Insert template", "插入模板")}
              </Button>
              <Button variant="elevated" onClick={() => clearCustomCss()}>
                {text("Clear", "清空")}
              </Button>
            </div>
          </div>
          <Textarea
            className="max-h-96 min-h-40 font-mono"
            aria-label={text("Custom CSS", "自定义 CSS")}
            value={customCss}
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            placeholder={CUSTOM_CSS_TEMPLATE}
            onChange={(e) => setCustomCss(e.target.value)}
          />
        </SettingsRow>

        <SettingsRow label={t("general.font")}>
          <SettingsDropdown
            value={font}
            options={FONT_SELECT_OPTIONS}
            onChange={setFont}
            label={t("general.font")}
          />
        </SettingsRow>

        <SettingsRow
          label={text("Equal-width digits (numbers in lists and menus line up)", "数字等宽（列表和菜单里的数字上下对齐）")}
          htmlFor="tabular-nums"
        >
          <Switch id="tabular-nums" checked={tabularNums} onCheckedChange={setTabularNums} />
        </SettingsRow>

        <SettingsRow label={t("general.language")}>
          <SettingsDropdown
            value={locale}
            options={LANG_OPTIONS}
            onChange={setLocale}
            label={t("general.language")}
          />
        </SettingsRow>

        <SettingsRow label={text("Conversation view", "对话显示方式")}>
          <SettingsDropdown
            value={transcriptView}
            options={[
              { value: "normal", label: text("Normal", "普通") },
              { value: "thinking", label: text("Thinking", "显示思考") },
              { value: "verbose", label: text("Verbose", "详细") },
            ]}
            onChange={setDefaultTranscriptView}
            label={text("Conversation view", "对话显示方式")}
          />
        </SettingsRow>

        <SettingsRow label={text("Chat width", "聊天宽度")}>
          <SettingsDropdown
            value={chatWidth}
            options={[
              { value: "narrow", label: text("Narrow", "窄") },
              { value: "full", label: text("Full width", "全宽") },
            ]}
            onChange={setChatWidth}
            label={text("Chat width", "聊天宽度")}
          />
        </SettingsRow>

        <SettingsRow
          label={text("Suggest your next message after each reply (Tab to use it; one extra model call per turn)",
            "每次回复后建议下一句（按 Tab 采用；每轮多一次模型调用）")}
          htmlFor="composer-predictions"
        >
          <Switch id="composer-predictions" checked={predictions} onCheckedChange={setComposerPredictions} />
        </SettingsRow>
      </SettingsSection>

      <UserSection />

      <DesktopAttentionSection />

      <ApplicationSection />
    </SettingsPage>
  );
}

function ThemeChoices({
  name,
  value,
  onChange,
  options,
}: {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; theme: string }[];
}) {
  // Compact tiles in one row: a mini window preview, then the radio and
  // its label. The selected tile's preview carries the same accent ring
  // as a selected colour swatch.
  return (
    <RadioGroup value={value} onValueChange={onChange} className="flex flex-wrap gap-3">
      {options.map((option) => (
        <label key={option.value} htmlFor={`${name}-${option.value}`} className={styles.themeTile}>
          <span className={styles.themeSwatch} data-theme={option.theme} aria-hidden="true">
            <span className={styles.themeDot} style={{ background: "var(--accent-orange)" }} />
            <span className={styles.themeDot} style={{ background: "var(--accent-green)" }} />
            <span className={styles.themeDot} style={{ background: "var(--text-primary)" }} />
          </span>
          <span className="flex items-center gap-2">
            <RadioGroupItem value={option.value} id={`${name}-${option.value}`} />
            <span className="text-fs-base">{option.label}</span>
          </span>
        </label>
      ))}
    </RadioGroup>
  );
}

/** One colour picker for every colour row: round preset swatches, a
 *  custom-colour well (native picker behind a pipette) and Reset, in
 *  that order, left-aligned under the row's label. */
function ColorSwatches({
  label,
  customLabel,
  resetLabel,
  presets,
  value,
  onPick,
  onReset,
  resetDisabled,
}: {
  label: string;
  customLabel: string;
  resetLabel: string;
  presets: readonly string[];
  value: string;
  onPick: (hex: string) => void;
  onReset: () => void;
  resetDisabled: boolean;
}) {
  const current = value.toLowerCase();
  const isPreset = presets.some((hex) => hex.toLowerCase() === current);
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      {presets.map((hex) => (
        <button
          key={hex}
          type="button"
          className={styles.swatch}
          style={{ background: hex }}
          aria-label={hex}
          aria-pressed={hex.toLowerCase() === current}
          onClick={() => onPick(hex)}
        />
      ))}
      <label
        className={styles.swatchCustom}
        data-active={isPreset ? undefined : ""}
        style={isPreset ? undefined : { background: value }}
      >
        <input
          type="color"
          className="sr-only"
          aria-label={customLabel}
          value={value}
          onChange={(e) => onPick(e.target.value)}
        />
        <SolarIcon name="pipette" size={14} aria-hidden="true" />
      </label>
      <Button
        variant="elevated"
        className="ml-1"
        onClick={onReset}
        disabled={resetDisabled}
      >
        {resetLabel}
      </Button>
    </div>
  );
}
