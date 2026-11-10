"use client";

import { settingsSend } from "@/lib/settings/settings-request";

/**
 * LLM Providers settings — port of /js/shared/settings-providers.js (521 lines).
 *
 * Two-pane layout: provider list (search + grouped by enabled/disabled)
 * on the left; detail pane on the right with enable toggle, API key
 * input (masked status and explicit replacement), base URL override,
 * connectivity check, and
 * model list (toggle / search / fetch remote / bulk enable / disable).
 *
 * Originally a single 800-line file (providers-section.tsx); now split
 * into one file per sub-component:
 *   - types.ts: Provider / Model / formatCtx
 *   - provider-item.tsx, detail.tsx, setup-hint.tsx
 *   - api-key.tsx (exported for /settings/search), base-url.tsx,
 *     connectivity.tsx, model-list.tsx
 */
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Waypoints } from "lucide-react";

import { Detail } from "./detail";
import { RoutingOverview } from "./routing-overview";
import { ProviderItem } from "./provider-item";
import { AddCustomProvider } from "./add-custom-provider";
import type { Provider } from "./types";
import { SettingsPage } from "../settings-ui";
import styles from "./provider-pane.module.css";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import { cachedFetch, invalidate, readCachedSettings } from "@/lib/prefs/settings-cache";
import { refreshAgentChip } from "./types";
import { useTranslation } from "@/lib/i18n";
import { pushPath } from "@/lib/nav/shallow-nav";

// Re-export ApiKey for search-providers-section.tsx (the only other
// consumer outside this subdirectory).
export { ApiKey } from "./auth/api-key";
export type { Provider, Model } from "./types";

export function ProvidersSection({ initialProviderId }: { initialProviderId?: string } = {}) {
  const { t, text } = useTranslation();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [providers, setProviders] = useState<Provider[]>(() => readCachedSettings<{ providers?: Provider[] }>("/api/providers/list")?.providers ?? []);
  // Selection lives in the URL: /settings/providers/<id> selects <id>,
  // /settings/providers (no id) falls back to the first enabled provider.
  // ``initialProviderId`` is the route param so a hard refresh / shared
  // link lands on the right provider; clicking a row shallow-pushes the
  // new URL, which re-renders this with a new initialProviderId.
  // /settings/providers with no id opens the Overview; a provider id opens
  // that provider. ``fallbackSelectedId`` is only the post-delete reset.
  const [fallbackSelectedId, setSelectedId] = useState<string | null>(null);
  const selectedId = initialProviderId ?? fallbackSelectedId;
  const [search, setSearch] = useState("");
  const sidebarRef = useRef<HTMLDivElement>(null);

  // Sidebar scroll is intentionally CONTAINED — see the matching
  // `overscroll-behavior: contain` in settings-page.module.css. The
  // previous version forwarded wheel deltas from the sidebar onto the
  // page scroller once the list hit its boundary; that made the right
  // detail column drift up/down while the user was just trying to
  // scroll the provider list, which read as a bug.

  // Why the last read of the list failed. A failed read keeps the list
  // already shown and says so, rather than showing no providers at all.
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      // ``cachedFetch`` shares in-flight promises and keeps successful
      // responses for 30s, so tab-switching back here within that
      // window is instant. Mutations call ``invalidate()`` below to
      // force the next read to hit the network.
      const d = await cachedFetch<{ providers?: Provider[] }>("/api/providers/list");
      setProviders(d.providers || []);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error && err.message ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    const refreshProviders = () => {
      invalidate("/api/providers/list");
      void reload();
    };
    window.addEventListener("op:provider-models-changed", refreshProviders);
    return () => window.removeEventListener("op:provider-models-changed", refreshProviders);
  }, [reload]);

  // Navigate to /settings/providers/<id> instead of plain setState so the
  // URL is shareable and survives a refresh.
  const selectProvider = useCallback(
    (id: string) => {
      setSelectedId(id);
      pushPath(`/settings/providers/${encodeURIComponent(id)}`);
    },
    [],
  );

  const showOverview = useCallback(() => {
    setSelectedId(null);
    pushPath("/settings/providers");
  }, []);

  const enabled = providers.filter((p) => p.enabled);
  const disabled = providers.filter((p) => !p.enabled);
  const selected = providers.find((p) => p.id === selectedId) || null;

  function matches(p: Provider) {
    if (!search) return true;
    const q = search.toLowerCase();
    return p.label.toLowerCase().includes(q) || p.id.toLowerCase().includes(q);
  }

  async function toggleProvider(id: string, en: boolean) {
    await settingsSend(`/api/providers/${encodeURIComponent(id)}/toggle`, {
      body: { enabled: en },
      failure: text("Could not change this provider. Try again.", "无法更改这个 Provider，请重试。"),
    });
    invalidate("/api/providers/list");
    reload();
    // Disabling/enabling a provider changes which models the chat picker
    // may show — drop the React-Query cache the composer + model badge
    // read so a disabled provider's models vanish from the top menu
    // without a page reload (the backend already excludes them).
    queryClient.invalidateQueries({ queryKey: ["models-enabled"] });
    // The top-bar agent chip reads agentSettings, not the query cache —
    // refetch it so disabling the current model's provider clears the chip.
    refreshAgentChip();
  }

  return (
    <SettingsPage
      title={t("settings.tab.providers")}
      description={text(
        "Enable an LLM backend, paste an API key (or rely on local OAuth / subscription), and pick which models the chat composer exposes.",
        "启用大模型后端，填写 API key（或使用本地 OAuth / 订阅），并选择聊天输入框可用的模型。",
      )}
      bodyClassName="gap-0 overflow-hidden p-0"
    >
        <div className={styles.providersLayout}>
          <div className={styles.providersSidebar} ref={sidebarRef}>
            <div className="p-[0_0_8px]">
              <div className="flex items-center w-full min-w-0">
                <div className="w-full min-w-0">
                  <SearchInput
                    placeholder={text("Search providers...", "搜索 Provider...")}
                    value={search}
                    onChange={setSearch}
                  />
                </div>
              </div>
              <AddCustomProvider
                onCreated={(id) => {
                  invalidate("/api/providers/list");
                  reload().then(() => selectProvider(id));
                }}
              />
            </div>
          <div className={`${styles.providerListItems} flex flex-col gap-[1px]`}>
          <button
            type="button"
            className={styles.providerItem + (selectedId === null ? " " + styles.active : "")}
            onClick={showOverview}
            aria-current={selectedId === null ? "true" : undefined}
          >
            <span className={styles.overviewIcon}><Waypoints size={14} strokeWidth={1.75} aria-hidden /></span>
            <span className={styles.providerLabel}>{text("Overview", "总览")}</span>
          </button>
          {loadError ? (
            <div className={styles.loadError} role="alert">
              <p className={styles.loadErrorText}>
                {text("Couldn't load the provider list: ", "无法读取 Provider 列表：")}
                {loadError}
              </p>
              <Button
                variant="elevated"
                size="sm"
                onClick={() => {
                  invalidate("/api/providers/list");
                  void reload();
                }}
              >
                {text("Retry", "重试")}
              </Button>
            </div>
          ) : null}
          {enabled.filter(matches).length > 0 && (
            <>
              <div className={styles.providersGroupLabel}>{text("Enabled", "已启用")}</div>
              {enabled.filter(matches).map((p) => (
                <ProviderItem
                  key={p.id}
                  p={p}
                  active={selectedId === p.id}
                  onSelect={selectProvider}
                />
              ))}
            </>
          )}
          {disabled.filter(matches).length > 0 && (
            <>
              <div className={styles.providersGroupLabel}>{text("Not enabled", "未启用")}</div>
              {disabled.filter(matches).map((p) => (
                <ProviderItem
                  key={p.id}
                  p={p}
                  active={selectedId === p.id}
                  onSelect={selectProvider}
                />
              ))}
            </>
          )}
          </div>
        </div>
          <div className={styles.detail}>
            {selectedId === null ? (
              <RoutingOverview providers={providers} onSelectProvider={selectProvider} />
            ) : !selected ? (
              <div className={styles.detailEmpty}>{text("Select a provider on the left", "选择左侧 Provider")}</div>
            ) : (
              <Detail
                key={selected.id}
                provider={selected}
                onToggle={(en) => toggleProvider(selected.id, en)}
                onChanged={() => reload()}
                onDeleted={() => {
                  invalidate("/api/providers/list");
                  setSelectedId(null);
                  queryClient.invalidateQueries({ queryKey: ["models-enabled"] });
                  refreshAgentChip();
                  router.push("/settings/providers");
                  reload();
                }}
              />
            )}
          </div>
        </div>
    </SettingsPage>
  );
}
