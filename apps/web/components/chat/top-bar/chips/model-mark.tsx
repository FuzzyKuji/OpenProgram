/**
 * The model chip's icon: the logo of the provider the model is called
 * through (OpenAI, Anthropic, OpenRouter...), the same logos the
 * Settings provider list shows. Providers without a logo (custom,
 * local, generic OpenAI-compatible endpoints) show the chip glyph,
 * which says "a model" without naming a maker it may not be.
 *
 * A one-colour logo is drawn in the text colour through a mask, so it
 * follows the theme; a coloured one is the brand's own picture. On
 * hover it pops like every other icon in a control.
 *
 * The logos are drawn edge to edge, while a Solar glyph keeps its ink
 * inside the middle 20 of its 24 units. So a logo is drawn at that share
 * of the box (LOGO_INK, 13.3 px in a 16 px box), centred, or it reads a
 * size larger than the icons beside it.
 */
"use client";

import { useEffect, useRef } from "react";
import { motion, useAnimation, useReducedMotion } from "framer-motion";

import { SolarIcon } from "@/components/solar-icons";
import { providerLogo } from "@/components/settings/providers/icons/provider-icon";
import { HOVER_POP, HOVER_SPRING, followHostHover } from "@/components/ui/hover-pop";
import { cn } from "@/lib/utils";

/** Shown when the provider has no logo. */
export const MODEL_FALLBACK_ICON = "cpu";

/** The share of the box a logo is drawn at: a Solar glyph's live area. */
export const LOGO_INK = 20 / 24;

export function ModelMark({ provider, size = 16, className }: { provider?: string; size?: number; className?: string }) {
  const logo = providerLogo(provider);
  const url = logo?.url;
  const self = useRef<HTMLSpanElement>(null);
  const pop = useAnimation();
  const reduced = useReducedMotion();

  useEffect(() => {
    const element = self.current;
    if (!url || !element || reduced) return;
    return followHostHover(element, () => void pop.start("animate"), () => void pop.start("normal"));
  }, [url, pop, reduced]);

  if (!logo) {
    return <SolarIcon name={MODEL_FALLBACK_ICON} size={size} className={cn("shrink-0", className)} aria-hidden="true" />;
  }
  const box = { width: size, height: size };
  const ink = Math.round(size * LOGO_INK * 100) / 100;
  const inner = { width: ink, height: ink };
  return (
    <motion.span
      ref={self}
      data-provider-logo={provider}
      aria-hidden="true"
      className={cn("inline-flex shrink-0 items-center justify-center", className)}
      style={box}
      variants={HOVER_POP}
      initial="normal"
      animate={pop}
      transition={HOVER_SPRING}
    >
      {logo.mono ? (
        <span
          className="bg-current"
          style={{
            ...inner,
            mask: `url("${logo.url}") center / contain no-repeat`,
            WebkitMask: `url("${logo.url}") center / contain no-repeat`,
          }}
        />
      ) : (
        <img src={logo.url} alt="" width={ink} height={ink} style={inner} className="object-contain" />
      )}
    </motion.span>
  );
}
