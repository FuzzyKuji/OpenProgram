// Always-on in the reader's words: wake outcomes, Goal states and where a
// report was sent. Shared by Agents → Always-on and the Activity panel.
import type {
  AlwaysOnChannelTarget, AlwaysOnDelivery, AlwaysOnQuietHours, AlwaysOnWakeOutcome,
} from "@/lib/agents/always-on";
import { channelName } from "@/lib/chat/transcript/channel-speaker";

type Text = (en: string, zh: string) => string;

export function outcomeLabel(outcome: AlwaysOnWakeOutcome, text: Text): string {
  switch (outcome) {
    case "disabled": return text("Always-on was off", "常驻未开启");
    case "quiet": return text("Skipped: quiet hours", "跳过：安静时段");
    case "busy": return text("Skipped: a turn was running", "跳过：会话正在运行");
    case "goal_started": return text("Started the standing goal", "已开始常驻目标");
    case "goal_in_progress": return text("Goal in progress", "目标进行中");
    case "goal_paused": return text("Goal paused", "目标已暂停");
    case "check_in": return text("Checked in", "已巡检");
    case "idle": return text("Nothing to do", "无事可做");
  }
}

export function goalStatusLabel(status: string, text: Text): string {
  const labels: Record<string, string> = {
    active: text("In progress", "进行中"),
    paused: text("Paused", "已暂停"),
    achieved: text("Achieved", "已达成"),
    blocked: text("Blocked", "受阻"),
    cancelled: text("Cancelled", "已取消"),
    cleared: text("Cleared", "已清除"),
    failed: text("Failed", "失败"),
    impossible: text("Impossible", "无法完成"),
  };
  return labels[status] ?? status;
}

/** Monday first, as wake_days counts them. */
export function weekdayNames(text: Text): string[] {
  return [
    text("Mon", "周一"), text("Tue", "周二"), text("Wed", "周三"), text("Thu", "周四"),
    text("Fri", "周五"), text("Sat", "周六"), text("Sun", "周日"),
  ];
}

/** When scheduled wakes may happen, or "" when that is always. */
export function scheduleLabel(config: { quiet_hours?: AlwaysOnQuietHours | null; wake_days?: number[] }, text: Text): string {
  const parts: string[] = [];
  const days = config.wake_days ?? [];
  if (days.length && days.length < 7) {
    const names = weekdayNames(text);
    parts.push(days.map((day) => names[day]).join(text(", ", "、")));
  }
  if (config.quiet_hours) {
    const { start, end } = config.quiet_hours;
    parts.push(text(`quiet ${start}–${end}`, `${start}–${end} 安静`));
  }
  return parts.join(" · ");
}

export function targetLabel(target: AlwaysOnChannelTarget, text: Text): string {
  return `${channelName(target.channel, text)} · ${target.label || target.peer_id}`;
}

function deliveryError(error: string | undefined, text: Text): string {
  switch (error) {
    case "auth": return text("the account is not signed in", "账号未登录或凭据失效");
    case "rate_limit": return text("rate limited", "发送过于频繁");
    case "bad_target": return text("the conversation was not found", "找不到该会话");
    case "network": return text("network error", "网络错误");
    case "not_supported": return text("not supported on this channel", "此渠道不支持");
    default: return text("unknown error", "未知错误");
  }
}

export function deliveryLabel(delivery: AlwaysOnDelivery, text: Text): string {
  const where = targetLabel(delivery, text);
  if (delivery.status === "sent") return text(`Sent to ${where}`, `已发送到 ${where}`);
  if (delivery.status === "sending") return text(`Sending to ${where}…`, `正在发送到 ${where}…`);
  const reason = deliveryError(delivery.error, text);
  return text(`Not sent to ${where}: ${reason}`, `未能发送到 ${where}：${reason}`);
}
