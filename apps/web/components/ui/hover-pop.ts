/**
 * The hover motion every icon in a control shares: hovering the control
 * makes its icon pop, 1.12 times its size, on one spring.
 *
 * An icon finds the control from inside: the nearest clickable ancestor
 * (HOVER_HOST), or the icon itself when it sits in none. Solar glyphs
 * (../solar-icons/solar-icon.tsx) and Agent characters
 * (../avatar/bot/bot-avatar.ts) both use it, so a chip or menu row moves
 * its picture the same way whatever the picture is.
 */
import type { Transition, Variants } from "framer-motion";

/** The elements whose hover drives the icon inside them. */
export const HOVER_HOST =
  'button, a, summary, [role="button"], [role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"], [role="option"], .folder-pill-seg, .runtime-badge, .status-badge';

export const HOVER_SPRING: Transition = { type: "spring", stiffness: 420, damping: 16, mass: 0.8 };

export const HOVER_POP_SCALE = 1.12;

export const HOVER_POP: Variants = { normal: { scale: 1 }, animate: { scale: HOVER_POP_SCALE } };

/** The element whose hover moves the icon `self`. */
export function hoverHostOf(self: Element): Element {
  return self.parentElement?.closest(HOVER_HOST) ?? self;
}

/** Call `enter` and `leave` as the pointer enters and leaves `self`'s
 *  hover host. Returns the function that stops listening. */
export function followHostHover(self: Element, enter: () => void, leave: () => void): () => void {
  const host = hoverHostOf(self);
  host.addEventListener("mouseenter", enter);
  host.addEventListener("mouseleave", leave);
  return () => {
    host.removeEventListener("mouseenter", enter);
    host.removeEventListener("mouseleave", leave);
  };
}
