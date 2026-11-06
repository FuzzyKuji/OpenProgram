"use client";

/**
 * The background memory writer's health, said in words.
 *
 * The writer runs out of sight; when it stops, conversations quietly stop
 * reaching memory. `/api/memory/status` carries its last outcome and the
 * worker announces a failure nothing will retry as a `memory_writer_failed`
 * frame. Both surfaces read the reason through `writerFailureText`.
 */
import { useEffect, useState } from "react";
import { CircleAlert } from "lucide-react";

import { translateText, useTranslation } from "@/lib/i18n";
import { formatDate } from "./markdown/format";
import styles from "./memory-page.module.css";

const REASONS: Record<string, [string, string]> = {
  MODEL_AUTHENTICATION: ["the writer model's sign-in is no longer valid, and no other model worked", "写入用的模型登录已失效，换别的模型也没成功"],
  MODEL_AUTHORIZATION: ["the writer model refused this account, and no other model worked", "写入用的模型拒绝了这个账号，换别的模型也没成功"],
  MODEL_RATE_LIMIT: ["the writer model's usage limit was reached", "写入用的模型达到用量上限"],
  MODEL_INVALID_REQUEST: ["the writer model rejected the request, and no other model worked", "写入用的模型拒绝了请求，换别的模型也没成功"],
  MODEL_CONTEXT_LENGTH: ["the conversation is too long for the writer model", "对话超出了写入模型的上下文长度"],
  MODEL_CONTENT_POLICY: ["the writer model declined the content", "写入用的模型拒绝处理这段内容"],
  MODEL_TRANSPORT: ["the writer model could not be reached", "连不上写入用的模型"],
  MODEL_TIMEOUT: ["the writer model timed out", "写入用的模型超时"],
  MODEL_PROVIDER_INTERNAL: ["the writer model's service failed", "写入用的模型服务出错"],
  MEMORY_PROVIDER_RESOLUTION_FAILED: ["no model is available for writing memory", "没有可用于写记忆的模型"],
  WRITER_NO_PROGRESS: ["the writer's edits kept failing the memory checks", "写入的内容一直没通过记忆格式检查"],
  COMMIT_REJECTED: ["the writer's edits still failed the memory checks after it was sent back to fix them", "写入的内容退回修改后仍没通过记忆格式检查"],
  INVALID_TOPIC_FORMAT: ["a topic file is broken and the repair agent could not fix it yet", "有个主题文件格式坏了，修复 agent 暂时没修好"],
  CONCURRENT_UPDATE: ["memory was being changed elsewhere; it retries on its own", "记忆正被别处修改，会自动重试"],
  GIT_COMMIT_FAILED: ["memory changed but its history could not be saved", "记忆已修改，但历史记录保存失败"],
};

export function writerFailureText(reasonCode: string | null | undefined): string {
  const pair = reasonCode ? REASONS[reasonCode] : undefined;
  return pair ? translateText(pair[0], pair[1]) : translateText("an unexpected error", "未知错误");
}

interface WriterStatus {
  last_outcome: "success" | "failure" | null;
  last_success_at: string | null;
  last_failure: { at: string; reason_code: string; retryable: boolean } | null;
  pending_turns?: number;
}

/** A strip above the memory sections while the writer's last run failed. */
export function WriterHealthBanner({ statusUrl }: { statusUrl: string }) {
  const { text, locale } = useTranslation();
  const [writer, setWriter] = useState<WriterStatus | null>(null);

  useEffect(() => {
    let live = true;
    fetch(statusUrl)
      .then((r) => (r.ok ? r.json() : null))
      .then((status) => { if (live) setWriter(status?.writer ?? null); })
      .catch(() => {});
    return () => { live = false; };
  }, [statusUrl]);

  if (writer?.last_outcome !== "failure" || !writer.last_failure) return null;
  const since = writer.last_success_at ? Date.parse(writer.last_success_at) / 1000 : 0;
  const pending = writer.pending_turns ?? 0;
  const detail = [
    since
      ? text(`last written ${formatDate(since, locale)}`, `上次写入成功：${formatDate(since, locale)}`)
      : text("nothing written yet", "还没有成功写入过"),
    pending > 0 ? text(`${pending} turns waiting`, `${pending} 轮对话待写入`) : "",
  ].filter(Boolean).join(" · ");

  return (
    <div className={styles.writerBanner} role="alert">
      <CircleAlert size={16} aria-hidden />
      <span>
        {text("Conversations are not reaching memory: ", "对话没有写进记忆：")}
        {writerFailureText(writer.last_failure.reason_code)}
        {writer.last_failure.retryable ? text("; retrying on its own", "；会自动重试") : ""}
      </span>
      <span className={styles.writerBannerDetail}>{detail}</span>
    </div>
  );
}
