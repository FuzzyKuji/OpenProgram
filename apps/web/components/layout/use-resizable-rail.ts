"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";

// Keep in sync with --rail-collapsed-w in app/styles/design/layout.css.
const COLLAPSED_RAIL_WIDTH = 63;
// The rail moves the whole centre column, so the curve starts from rest:
// one that front-loads the travel puts a third of it into the first frame.
export const RAIL_MOVE_MS = 200;
export const RAIL_EASING = "cubic-bezier(0.4, 0, 0.2, 1)";
const RAIL_TRANSITION = `width ${RAIL_MOVE_MS}ms ${RAIL_EASING}, min-width ${RAIL_MOVE_MS}ms ${RAIL_EASING}`;
// A move whose width does not report its end settles after this.
const SETTLE_FALLBACK_MS = RAIL_MOVE_MS + 120;

/** Makes the rail's open-only parts (`.rail-open-only`, outermost ones)
 *  inert or not, on the elements themselves. */
function setOpenOnlyInert(shell: HTMLElement | null, inert: boolean) {
  if (!shell) return;
  for (const part of shell.querySelectorAll<HTMLElement>(".rail-open-only")) {
    // An inner part is inert with its outer one.
    if (part.parentElement?.closest(".rail-open-only")) continue;
    if (part.hasAttribute("inert") === inert) continue;
    if (inert) part.setAttribute("inert", "");
    else part.removeAttribute("inert");
  }
}

interface ResizableRailOptions {
  open: boolean;
  minWidth: number;
  maxWidth: number;
  defaultWidth: number;
  direction: 1 | -1;
}

/** The rail's width, its resize handle, and when a close has settled.
 *
 *  Opening and closing change only the shell's width, in the click's
 *  frame, and the rail's `.collapsed` class, which the rails set from
 *  `open` in the same render. Nothing inside the rail mounts, unmounts or
 *  changes its display on either move (styles/base/layout.css, "Opening
 *  and closing"): what only the open rail shows stays mounted at the open
 *  width and fades, what both states show stays put or moves with the
 *  card's edge on the width's own duration and curve, which the shell
 *  passes down as --rail-move-duration and --rail-move-easing. */
export function useResizableRail({
  open,
  minWidth,
  maxWidth,
  defaultWidth,
  direction,
}: ResizableRailOptions) {
  const [width, setWidth] = useState(defaultWidth);
  const [resizing, setResizing] = useState(false);
  // Closed, and the close has arrived: false from the render that opens,
  // true once a close's width has settled (its transitionend, or the timer
  // behind it). Nothing visible keys on it; it is for what may change only
  // once the rail is at rest collapsed (the narrow layout's flow and drawer
  // shadow, the left sidebar's scroll position, paused animations).
  const [closedSettled, setClosedSettled] = useState(!open);
  if (open && closedSettled) setClosedSettled(false);
  // A close before the rail's first frame has been drawn is no move: it is
  // the mount restoring a stored closed rail (the left sidebar, under
  // html[data-sidebar-closed]), and nothing has been seen open.
  const drawn = useRef(false);
  useEffect(() => {
    const id = window.requestAnimationFrame(() => { drawn.current = true; });
    return () => window.cancelAnimationFrame(id);
  }, []);
  if (!open && !closedSettled && !drawn.current) setClosedSettled(true);
  // What only the open rail shows is unreachable (inert: no pointer, no
  // focus, out of the accessibility tree) from a close's settle to an
  // open's settle; while either move runs it is reachable or not as it was
  // at rest. The hook writes the attribute on the parts directly at the
  // settle, after the move: inert changes the whole subtree's style, and
  // in the click's frame it would restyle the whole conversation list
  // (as `pointer-events` and `visibility` did: 1,764 and 1,946 elements,
  // traced). Hidden by opacity alone, the parts change no inherited
  // property on a move (styles/base/layout.css).
  const shellRef = useRef<HTMLDivElement | null>(null);
  const inert = useRef(false);
  const settleInert = useCallback((next: boolean) => {
    inert.current = next;
    setOpenOnlyInert(shellRef.current, next);
  }, []);
  const settleClose = useCallback(() => {
    settleInert(true);
    setClosedSettled(true);
  }, [settleInert]);
  useEffect(() => {
    if (open || closedSettled) return;
    // transitionend settles it; the timer covers a rail whose width did
    // not change or whose transition was cut short.
    const timer = window.setTimeout(settleClose, SETTLE_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [open, closedSettled, settleClose]);
  useEffect(() => {
    if (!open || !inert.current) return;
    const timer = window.setTimeout(() => settleInert(false), SETTLE_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [open, settleInert]);
  // A closed mount (a stored closed rail) starts inert, and a part that
  // mounts while the rail is at rest closed (a first favourite) becomes
  // inert with it.
  useLayoutEffect(() => {
    if (closedSettled && !open) settleInert(true);
    else if (inert.current) setOpenOnlyInert(shellRef.current, true);
  });
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      // The handle stays mounted in both states; only the open rail resizes.
      if (event.button !== 0 || !open) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      dragRef.current = { startX: event.clientX, startWidth: width };
      setResizing(true);
    },
    [width, open],
  );

  const finishResize = useCallback(() => {
    dragRef.current = null;
    setResizing(false);
  }, []);

  // A close ends a drag: the width is no longer the handle's.
  useEffect(() => {
    if (!open && resizing) finishResize();
  }, [open, resizing, finishResize]);

  useEffect(() => {
    if (!resizing) return;
    window.addEventListener("pointerup", finishResize);
    window.addEventListener("pointercancel", finishResize);
    window.addEventListener("blur", finishResize);
    return () => {
      window.removeEventListener("pointerup", finishResize);
      window.removeEventListener("pointercancel", finishResize);
      window.removeEventListener("blur", finishResize);
    };
  }, [resizing, finishResize]);

  const onPointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      if (event.buttons === 0) {
        finishResize();
        return;
      }
      const next = drag.startWidth + (event.clientX - drag.startX) * direction;
      setWidth(Math.max(minWidth, Math.min(maxWidth, next)));
    },
    [direction, maxWidth, minWidth, finishResize],
  );

  const style = {
    width: `${open ? width : COLLAPSED_RAIL_WIDTH}px`,
    minWidth: `${open ? minWidth : COLLAPSED_RAIL_WIDTH}px`,
    transition: resizing ? "none" : RAIL_TRANSITION,
    // The open width: what only the open rail shows is laid out at it in
    // both states (styles/base/layout.css). It changes only while the
    // handle is dragged, never on opening or closing.
    "--rail-open-w": `${width}px`,
    // The rail's move as a duration and a curve, for what moves or fades
    // with the width inside it.
    "--rail-move-duration": `${RAIL_MOVE_MS}ms`,
    "--rail-move-easing": RAIL_EASING,
  } as CSSProperties;

  return {
    style,
    /** Closed and at rest: true once a close has arrived, false from the
     *  render that opens. */
    closedSettled,
    /** Spread on the rail's shell next to `style`. */
    shellProps: {
      ref: shellRef,
      "data-rail-closed": closedSettled ? "" : undefined,
      onTransitionEnd: (event: { target: EventTarget; currentTarget: EventTarget; propertyName: string }) => {
        if (event.target !== event.currentTarget || event.propertyName !== "width") return;
        if (!open) settleClose();
        else if (inert.current) settleInert(false);
      },
    },
    /** The handle is mounted in both states, at one place among the card's
     *  children: mounting it on open and removing it on close changed
     *  whether the rail's content was the card's first child, which
     *  restyled every element that a `:first-child` rule anywhere could
     *  match (2,000 in the left sidebar, about 20 ms of the click's frame,
     *  traced). Closed, or closing, it takes no pointer and is hidden from
     *  assistive technology (styles/base/layout.css). */
    resizeHandleProps: {
      className: "rail-resize-handle",
      "data-edge": direction === 1 ? "right" : "left",
      "data-off": open ? undefined : "",
      "aria-hidden": open ? undefined : true,
      "data-resizing": resizing,
      onPointerDown,
      onPointerMove,
      onPointerUp: finishResize,
      onPointerCancel: finishResize,
      onLostPointerCapture: finishResize,
    },
  };
}
