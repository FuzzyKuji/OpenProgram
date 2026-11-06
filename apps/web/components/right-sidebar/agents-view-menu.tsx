"use client";

/**
 * The Agents list's view menu: which agents to show and how to arrange
 * them. Built from the composer options menu's pieces (the same radix
 * wrapper, MENU_PANEL frame, value rows and check rows), so every popup
 * in the app reads alike.
 */
import { useRef, useState } from "react";
import { type AnimatedNavIconHandle, GalleryVerticalEndIcon } from "@/components/animated-icons";
import { MenuRow, type MenuGlyph } from "@/components/ui/menu/menu-parts";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { HoverTip } from "@/components/ui/tooltip";
import { MENU_ITEM_STATES, MENU_PANEL, MENU_SEPARATOR, itemCls } from "@/components/ui/menu/menu-styles";
import { useTranslation } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  DEFAULT_ACTIVITY_VIEW,
  setActivityView,
  useActivityView,
  type ActivityArrange,
  type ActivityShow,
} from "@/lib/prefs/activity-view";

function ValueSubmenu<T extends string>({ icon, label, value, options, onPick }: {
  icon: MenuGlyph; label: string; value: T; options: [T, string, MenuGlyph][]; onPick: (value: T) => void;
}) {
  return <DropdownMenuSub>
    <DropdownMenuSubTrigger className={cn(itemCls(false), MENU_ITEM_STATES)}>
      <MenuRow glyph={icon} label={<span className="flex min-w-0 items-center gap-1.5"><span className="min-w-0 flex-1 truncate">{label}</span><span className="shrink-0 text-text-muted">{options.find(([key]) => key === value)?.[1]}</span></span>} submenu />
    </DropdownMenuSubTrigger>
    <DropdownMenuSubContent className={cn(MENU_PANEL, "z-[201]")}>
      {options.map(([key, name, glyph]) => (
        <DropdownMenuItem key={key} className={cn(itemCls(false), MENU_ITEM_STATES)} onSelect={() => onPick(key)}>
          <MenuRow glyph={glyph} label={name} checked={key === value} />
        </DropdownMenuItem>
      ))}
    </DropdownMenuSubContent>
  </DropdownMenuSub>;
}

export function AgentsViewMenu() {
  const { text } = useTranslation();
  const view = useActivityView();
  const [open, setOpen] = useState(false);
  const iconRef = useRef<AnimatedNavIconHandle>(null);
  // A non-default view keeps the button lit, so a filter is never hidden.
  const changed = view.show !== DEFAULT_ACTIVITY_VIEW.show || view.arrange !== DEFAULT_ACTIVITY_VIEW.arrange;
  return <DropdownMenu open={open} onOpenChange={setOpen}>
    <HoverTip label={text("Show and arrange agents", "显示和排列 agent")}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={text("Show and arrange agents", "显示和排列 agent")}
          data-view-changed={changed ? "1" : "0"}
          onClick={event => event.stopPropagation()}
          onMouseEnter={() => iconRef.current?.startAnimation?.()}
          onMouseLeave={() => iconRef.current?.stopAnimation?.()}
          className={"flex size-(--ui-button-h-xs) items-center justify-center rounded-sm outline-none transition-colors hover:bg-bg-hover "
            + (open ? "bg-bg-hover " : "")
            + (open || changed ? "text-text-secondary" : "text-text-muted")}
        >
          <GalleryVerticalEndIcon ref={iconRef} size={20} />
        </button>
      </DropdownMenuTrigger>
    </HoverTip>
    <DropdownMenuContent align="end" sideOffset={6} className={cn(MENU_PANEL, "z-[200] min-w-[200px]")}>
      <ValueSubmenu<ActivityShow>
        icon="eye"
        label={text("Show", "显示")}
        value={view.show}
        options={[["all", text("All", "全部"), "list"], ["attention", text("Waiting for you", "等你处理"), "question-circle"], ["running", text("Running", "正在运行"), "play"]]}
        onPick={show => setActivityView({ show })}
      />
      <DropdownMenuSeparator className={MENU_SEPARATOR} />
      <ValueSubmenu<ActivityArrange>
        icon="structure"
        label={text("Arrange", "排列")}
        value={view.arrange}
        options={[["structure", text("By structure", "按结构"), "structure"], ["time", text("By time", "按时间"), "clock-circle"]]}
        onPick={arrange => setActivityView({ arrange })}
      />
    </DropdownMenuContent>
  </DropdownMenu>;
}
