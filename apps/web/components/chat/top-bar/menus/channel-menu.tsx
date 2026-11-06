"use client";

/**
 * Channel menu — the content of the channel chip's popover.
 *
 * The chip already says this is the channel, so the menu has no "Channel"
 * heading: it lists the enabled accounts grouped under their platform
 * name (WeChat, Telegram, …), checks the bound one, and offers
 * "Disconnect" only while one is bound. Picking an account mirrors the
 * conversation's messages to it; it never changes where the conversation
 * runs (that is the environment chip beside it).
 *
 * Positioning / click-outside / portal are handled by the shadcn
 * <Popover> that hosts it; this component just renders the rows.
 */
import { useTranslation } from "@/lib/i18n";
import { SolarIcon } from "@/components/solar-icons";
import { channelBrand, useChannelChoices } from "./channel-choices";
import {
  CHECK_SLOT_PAD,
  GROUP_LABEL,
  MENU_PANEL,
  MENU_SEPARATOR,
  MENU_TAG,
  itemCls,
} from "@/components/ui/menu/menu-styles";
import { MenuCheck } from "@/components/ui/menu/menu-check";

export function ChannelMenu({ onClose }: { onClose: () => void }) {
  const { text } = useTranslation();
  const { loaded, groups, current: cur, pick } = useChannelChoices();

  function choose(ch: string, acct: string) {
    onClose();
    pick(ch, acct);
  }

  return (
    <div className={MENU_PANEL}>
      {groups.map((g, i) => (
        <div key={g.plat}>
          {i > 0 ? <div className={MENU_SEPARATOR} /> : null}
          <div className={GROUP_LABEL}>{channelBrand(g.plat)}</div>
          {g.accounts.map((r) => {
            const active = r.channel === cur.channel && r.account_id === cur.account_id;
            const meta = r.name && r.name !== r.account_id ? r.name : "";
            return (
              <div
                key={r.channel + ":" + r.account_id}
                className={itemCls(false)}
                onClick={() => choose(r.channel, r.account_id)}
              >
                {/* Claude 实测：别名 tag 紧贴账号名左侧成簇，右缘只留勾位。 */}
                <span className="flex min-w-0 flex-1 items-center gap-[6px]">
                  <span className="truncate">{r.account_id}</span>
                  {meta ? <span className={MENU_TAG}>{meta}</span> : null}
                </span>
                {active ? (
                  <MenuCheck />
                ) : (
                  <span className={CHECK_SLOT_PAD} />
                )}
              </div>
            );
          })}
        </div>
      ))}

      {loaded && groups.length === 0 ? (
        <div className={`${GROUP_LABEL} whitespace-normal`}>
          {text("No chat app accounts yet.", "还没有可用的聊天软件账号。")}
        </div>
      ) : null}

      <div className={MENU_SEPARATOR} />
      {cur.channel ? (
        <div className={itemCls(false)} onClick={() => choose("", "")}>
          <SolarIcon name="close-circle" size={16} aria-hidden="true" />
          <span className="flex-1 truncate">{text("Disconnect", "断开")}</span>
        </div>
      ) : null}
      <a
        href="/settings/channels"
        onClick={onClose}
        className={`${itemCls(false)} no-underline`}
      >
        <SolarIcon name="settings-minimalistic" size={16} aria-hidden="true" />
        <span className="flex-1 truncate">{text("Manage channels", "管理渠道")}</span>
        <SolarIcon name="alt-arrow-right" size={14} className="text-text-muted" />
      </a>
    </div>
  );
}
