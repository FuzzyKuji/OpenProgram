"use client";

import { BrandMark, type BrandLogo } from "@/components/brand-mark";

import icons from "./provider-icons.json";
import styles from "../provider-pane.module.css";

export type ProviderLogo = BrandLogo;

/** The brand logo shipped for a provider id, or null when there is none
 *  (custom, local and generic OpenAI-compatible providers). */
export function providerLogo(id: string | undefined): ProviderLogo | null {
  const icon = id ? (icons as Record<string, { file: string; mono: boolean }>)[id] : undefined;
  return icon ? { url: `/images/providers/${icon.file}`, mono: icon.mono } : null;
}

/** The plate's padding around the logo, in px (provider-pane.module.css). */
const PLATE_PADDING = 2;

/** A provider's logo on the tinted plate Settings lists it with, which
 *  keeps mono marks visible on every theme: the whole logo fitted inside
 *  the plate's padding, still on hover. Unknown and custom providers keep
 *  an initial. */
export function ProviderIcon({ id, size = 24 }: { id: string; size?: number }) {
  const icon = providerLogo(id);
  const dimensions = { width: size, height: size };
  if (icon) {
    return (
      <span className={styles.providerIcon} style={dimensions} aria-hidden="true">
        <BrandMark logo={icon} size={size - 2 * PLATE_PADDING} color="var(--text-primary)" lazy />
      </span>
    );
  }
  return (
    <span className={styles.providerIconLetter} style={dimensions}>
      {(id[0] || "?").toUpperCase()}
    </span>
  );
}
