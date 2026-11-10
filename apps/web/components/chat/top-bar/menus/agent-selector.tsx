"use client";

/**
 * Model selector — the content of the chat model `<AgentBadge />`
 * popover.
 *
 * Lists every model the user enabled in Settings, grouped by provider.
 * With more than one provider the panel lists providers and each opens
 * its models in a DropdownMenuSub, the same submenu the sidebar's
 * conversation menu uses (hover, click or →, Radix's pointer grace);
 * the provider of the current model shows that model's name where the
 * others show a count.
 * Chat picks always pin the current conversation (`/api/model`), using
 * the draft `local_*` id when the backend has not acked yet.
 *
 * Positioning / click-outside / portal are handled by the shadcn
 * <DropdownMenu> in `index.tsx`; this file renders its rows.
 */

import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";

import { useBoundChat } from "../bound-chat";
import { api } from "@/lib/net/api";
import { updatePendingAgentModel } from "@/lib/agents/start-conversation";
import { useTranslation } from "@/lib/i18n";
import {
  CHECK_SLOT_PAD,
  GROUP_LABEL,
  MENU_ITEM_STATES,
  MENU_NOTE,
  MENU_PANEL,
  itemCls,
} from "@/components/ui/menu/menu-styles";
import { MenuCheck } from "@/components/ui/menu/menu-check";
import { SolarIcon } from "@/components/solar-icons";
import { ModelMark } from "../chips/model-mark";
import {
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { showToast } from "@/lib/format-utils/toast";

type EnabledModel = Awaited<ReturnType<typeof api.listEnabledModels>>[number];

export function AgentSelector({
  currentProvider,
  currentModel,
  onClose,
}: {
  currentProvider?: string;
  currentModel?: string;
  onClose: () => void;
}) {
  const { sessionId: currentSessionId, chatKey } = useBoundChat();
  const { t, text } = useTranslation();
  const { data: models } = useQuery({
    queryKey: ["models-enabled"],
    queryFn: api.listEnabledModels,
  });
  // Group headings name the provider as Settings does: the enabled list
  // carries the label, so the rows never show an id that a later fetch renames.
  const providerName = (id: string) => models?.find((m) => m.provider === id)?.providerLabel || id;

  async function pick(provider: string, model: string) {
    onClose();
    try {
      let sid: string | undefined =
        currentSessionId ||
        (chatKey && chatKey !== "__new__" ? chatKey : undefined);
      if (!sid) {
        const { useCenterTabs } = await import("@/lib/tabs/center-tabs-store");
        const { newSession } = await import("@/lib/runtime-bridge/session/conversations");
        const tabs = useCenterTabs.getState();
        const existing = tabs.tabs.find(
          (tab: { kind: string; draft?: boolean; sessionId?: string }) =>
            tab.kind === "session" && tab.draft && tab.sessionId,
        );
        sid = existing?.sessionId ?? tabs.openDraftSessionTab();
        if (!sid) return;
        newSession(sid);
      }
      if (await updatePendingAgentModel(sid, { provider, id: model })) return;
      await api.switchModel(provider, model, sid);
      // Only this conversation's model changes: the other split pane keeps
      // its own, and the global (focused) slot follows only for the focused
      // conversation. The fetch brings the new model's effort levels.
      const [{ useSessionStore }, { loadSessionAgentSettings }] = await Promise.all([
        import("@/lib/session-store"), import("@/lib/runtime-bridge/providers"),
      ]);
      const store = useSessionStore.getState();
      const own = store.agentSettingsBySession[sid];
      store.setSessionAgentSettings(sid, { ...own, chat: { provider, model } });
      if (sid === (store.activeChatKey ?? store.currentSessionId)) {
        store.setAgentSettings({ chat: { provider, model } });
      }
      void loadSessionAgentSettings(sid);
    } catch (e) {
      showToast(t("agent.switch_failed") + String(e), { tone: "error" });
    }
  }

  // Group enabled models by provider, preserving first-seen order.
  const byProvider: { provider: string; models: typeof models }[] = [];
  for (const m of models ?? []) {
    let group = byProvider.find((g) => g.provider === m.provider);
    if (!group) {
      group = { provider: m.provider, models: [] };
      byProvider.push(group);
    }
    group.models!.push(m);
  }

  const isActive = (m: EnabledModel) =>
    currentProvider === m.provider &&
    (currentModel === m.id || currentModel === `${m.provider}:${m.id}`);
  const modelRows = (list: EnabledModel[]) =>
    list.map((m) => (
      <ModelRow key={m.id} model={m} active={isActive(m)} onPick={() => pick(m.provider, m.id)} />
    ));

  return (
    <>
      {/* Grammar-A header naming the dimension. */}
      <div className={GROUP_LABEL}>{text("Models", "模型")}</div>
      {/* Nothing until the list arrives, or the empty-state note flashes. */}
      {!models ? null : models.length === 0 ? (
        <div className={MENU_NOTE}>
          {t("agent.no_enabled_models")}{" "}
          <a
            href="/settings/providers"
            onClick={onClose}
            className="text-accent-blue no-underline"
          >
            {t("agent.enable_models")} →
          </a>
        </div>
      ) : byProvider.length === 1 ? (
        // One provider has nothing to choose between: its models directly.
        <>
          <div className={GROUP_LABEL}>{providerName(byProvider[0].provider)}</div>
          {modelRows(byProvider[0].models!)}
        </>
      ) : (
        // One grid for every provider row: the model names start after the
        // longest provider name, so the columns never overlap row to row.
        <div className="grid grid-cols-[max-content_minmax(0,1fr)_auto]">
          {byProvider.map((group) => {
            const current = group.models!.find(isActive)?.name;
            return (
              <DropdownMenuSub key={group.provider}>
                <DropdownMenuSubTrigger
                  className={cn(itemCls(false), MENU_ITEM_STATES, "col-span-3 grid grid-cols-subgrid items-baseline gap-0")}
                >
                  {/* Baseline-aligned, so the smaller trailing text sits on
                      the label's line; the model name truncates first. */}
                  <span>
                    {/* Inline in the label's line, so the row keeps its text baseline. */}
                    <ModelMark provider={group.provider} className="mr-2 align-[-3px]" />
                    {providerName(group.provider)}
                  </span>
                  {current ? (
                    <span className="max-w-[164px] truncate justify-self-end pl-6 text-fs-xs text-text-secondary">{current}</span>
                  ) : (
                    <span className="justify-self-end pl-6 text-fs-xs text-text-muted">{group.models!.length}</span>
                  )}
                  <ChevronRight className="menu-row-chevron ml-1.5 size-4 self-center text-text-muted" aria-hidden="true" />
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent className={cn(MENU_PANEL, "text-text-primary")}>
                  {modelRows(group.models!)}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            );
          })}
        </div>
      )}
    </>
  );
}

function ModelRow({ model: m, active, onPick }: { model: EnabledModel; active: boolean; onPick: () => void }) {
  return (
    <DropdownMenuItem
      onSelect={onPick}
      // 选中不铺底色（hover 是唯一底色），选中态只靠右侧勾。
      className={cn(itemCls(false), MENU_ITEM_STATES)}
    >
      {/* Claude 实测：元数据（badge/能力/上下文窗）紧贴名字
          左侧成簇，不推到右缘——右缘只留勾位。 */}
      <span className="flex min-w-0 flex-1 items-center gap-[6px]">
        <span className="truncate">{m.name}</span>
        <CapIcons caps={m.capabilities} />
        {m.context ? (
          <span className="shrink-0 text-fs-2xs text-text-muted">
            {fmtCtx(m.context)}
          </span>
        ) : null}
      </span>
      {active ? <MenuCheck /> : <span className={CHECK_SLOT_PAD} />}
    </DropdownMenuItem>
  );
}

/** Capability icons — vision / video / tools / reasoning. `ctx` is
 *  dropped here (the context window already shows as a number). Solar
 *  glyphs, same roles the legacy `_CAP_ICONS` used in providers.js. */
function CapIcons({ caps }: { caps: string[] }) {
  const shown = caps.filter((c) => c !== "ctx");
  if (shown.length === 0) return null;
  return (
    <span className="flex shrink-0 items-center gap-[5px] text-text-muted">
      {shown.map((c) => {
        const icon = CAP_ICON[c];
        return icon ? (
          <span key={c} className="flex" data-tip={c[0].toUpperCase() + c.slice(1)}>
            {icon}
          </span>
        ) : null;
      })}
    </span>
  );
}

const CAP_ICON: Record<string, React.ReactNode> = {
  vision: <SolarIcon motionPreset="none" name="eye" size={14} />,
  video: <SolarIcon motionPreset="none" name="videocamera" size={14} />,
  // The briefcase fills its 24-unit box (y 2–21) while eye and camera
  // span 4–20, so at 14px it looked bigger and higher than its
  // neighbours; 12px gives it the same visual height and the same edges.
  tools: <SolarIcon motionPreset="none" name="case-minimalistic" size={12} />,
  reasoning: <SolarIcon motionPreset="none" name="lightbulb-bolt" size={14} />,
};

/** Compact context-window label: 200000 → "200k", 1048576 → "1M". */
function fmtCtx(n: number): string {
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}
