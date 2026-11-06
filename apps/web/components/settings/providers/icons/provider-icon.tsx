"use client";

import icons from "./provider-icons.json";
import styles from "../provider-pane.module.css";

export interface ProviderLogo {
  /** Where the SVG is served. */
  url: string;
  /** A one-colour mark drawn in the text colour (through a mask), rather
   *  than a picture in the brand's own colours. */
  mono: boolean;
}

/** The brand logo shipped for a provider id, or null when there is none
 *  (custom, local and generic OpenAI-compatible providers). */
export function providerLogo(id: string | undefined): ProviderLogo | null {
  const icon = id ? (icons as Record<string, { file: string; mono: boolean }>)[id] : undefined;
  return icon ? { url: `/images/providers/${icon.file}`, mono: icon.mono } : null;
}

/** Brand assets ship with the App; unknown/custom providers keep an initial. */
export function ProviderIcon({ id, size = 24 }: { id: string; size?: number }) {
  const icon = providerLogo(id);
  const dimensions = { width: size, height: size };
  if (icon) {
    const url = icon.url;
    return (
      <span className={styles.providerIcon} style={dimensions} aria-hidden="true">
        {icon.mono ? (
          <span style={{
            width: "100%", height: "100%", backgroundColor: "var(--text-primary)",
            mask: `url("${url}") center / contain no-repeat`,
            WebkitMask: `url("${url}") center / contain no-repeat`,
          }} />
        ) : (
          <img src={url} alt="" width={size} height={size} loading="lazy" />
        )}
      </span>
    );
  }
  return (
    <span className={styles.providerIconLetter} style={dimensions}>
      {(id[0] || "?").toUpperCase()}
    </span>
  );
}
