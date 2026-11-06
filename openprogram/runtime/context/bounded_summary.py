"""Bound text summarization without dropping any source on overflow."""
from __future__ import annotations

import asyncio

from openprogram.runtime.context.tokens import _text_tokens, estimate_history_tokens, real_context_window
from openprogram.models.providers.types import Context, SimpleStreamOptions, TextContent, UserMessage
from openprogram.models.providers.utils.overflow import is_context_overflow


async def summarize_text(text, model, options: SimpleStreamOptions, *, instruction: str,
                         max_tokens: int, remaining: list[int] | None = None) -> str:
    """Roll a bounded summary over every character; commit only on success.

    The mutable call allowance lets a request share one budget across evidence
    summaries and its final checkpoint. Provider overflow retries consume that
    same allowance. Authentication and other provider errors are not retried.
    """
    from openprogram.models.providers import complete_simple
    from openprogram.runtime.context.reactive import is_overflow_error
    from openprogram.models.usage import usage_scope

    window = real_context_window(model)
    output = min(max_tokens, model.max_tokens, max(1, window // 8))
    limit = window - output - max(256, window // 20) - _text_tokens(instruction)
    remaining = remaining if remaining is not None else [32]
    summary = ''
    position = 0
    source_cap = len(text)

    def context_for(chunk):
        # Prior output is data too: never upgrade a generated summary to system.
        prompt = (f'<previous-summary>\n{summary}\n</previous-summary>\n'
                  f'<source>\n{chunk}\n</source>')
        return Context(system_prompt=instruction, messages=[UserMessage(
            content=[TextContent(text=prompt)], timestamp=0)])

    async with asyncio.timeout(60):
        while position < len(text):
            if options.signal is not None and options.signal.is_set():
                raise asyncio.CancelledError()
            lo, hi = 0, min(len(text) - position, source_cap)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if estimate_history_tokens(context_for(text[position:position + mid]).messages) <= limit:
                    lo = mid
                else:
                    hi = mid - 1
            if lo == 0:
                raise ValueError('No input capacity for summarization')
            if remaining[0] <= 0:
                raise ValueError('Summary request budget exhausted')
            remaining[0] -= 1
            chunk = text[position:position + lo]
            context = context_for(chunk)
            summary_options = SimpleStreamOptions(
                max_tokens=output, signal=options.signal, api_key=options.api_key,
                headers=options.headers, transport=options.transport,
                max_retry_delay_ms=options.max_retry_delay_ms,
            )
            try:
                with usage_scope(call_kind='summarize'):
                    response = await complete_simple(model, context, summary_options)
            except Exception as exc:
                if not is_overflow_error(exc) or lo <= 1:
                    raise
                source_cap = lo // 2
                continue
            if response.stop_reason == 'aborted' or (options.signal is not None and options.signal.is_set()):
                raise asyncio.CancelledError()
            if is_context_overflow(response):
                if lo <= 1:
                    raise ValueError('Summary input exceeds provider context window')
                source_cap = lo // 2
                continue
            result = '\n'.join(b.text for b in response.content if isinstance(b, TextContent))
            if response.stop_reason in {'error', 'length', 'toolUse'} or not result.strip() or _text_tokens(result) > output:
                raise ValueError('Summarizer did not produce a complete bounded result')
            summary = result
            position += lo
    return summary
