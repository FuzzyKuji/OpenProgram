/**
 * The canvas's pointer gestures (dag/rendering.md §4), wired once per
 * pane by ``./canvas.ts``, which owns the view they move:
 *
 *   * mouse wheel or trackpad pinch → zoom about the cursor
 *   * two fingers on a trackpad → pan (``./wheel.ts`` tells them apart)
 *   * right (or middle) drag → pan, from anywhere on the graph
 *   * left drag on empty space → a box that selects (``../selection/selection.ts``;
 *     a left press on a node is a click on it)
 */

import { wheelKind } from "./wheel";
import { SelectionBand, clearSelection, releaseEditableFocus, select } from "../selection/selection";
import { _viewScale, _viewTx, _viewTy, setView } from "../../store/globals";

/** Zoom rates. A pinch (ctrlKey wheel) delivers small continuous
 *  deltas while a plain wheel delivers ±100-ish notches — one shared
 *  rate would make one of the two violent. */
const PINCH_ZOOM_RATE = 0.01;
export const WHEEL_ZOOM_RATE = 0.002;

/** What the gestures need from the view's owner. */
export interface Camera {
  /** Zoom by ``factor`` about the screen point ``(px, py)``. */
  zoomAt(px: number, py: number, factor: number): void;
  /** Close the screen-anchored cards before the view moves under them. */
  dismiss(): void;
  /** The store's view moved; paint it. */
  moved(): void;
}

/** Wire the pan / zoom gestures onto ``host`` once. */
export function wireGestures(host: HTMLElement, camera: Camera): void {
  const h = host as HTMLElement & { _dagCanvasWired?: boolean };
  if (h._dagCanvasWired) return;
  h._dagCanvasWired = true;

  host.addEventListener(
    "wheel",
    (e: WheelEvent) => {
      e.preventDefault();
      camera.dismiss();
      const rect = host.getBoundingClientRect();
      // A mouse wheel zooms about the cursor, the way a map does; two
      // fingers on a trackpad pan, and a pinch zooms at its own, faster
      // rate (./wheel.ts tells them apart). Line and page deltas (some
      // mice) are turned into pixels first.
      const kind = wheelKind(e);
      if (kind === "pan") {
        setView(_viewTx - e.deltaX, _viewTy - e.deltaY, _viewScale);
        camera.moved();
        return;
      }
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * 100 : e.deltaY;
      const rate = kind === "pinch" ? PINCH_ZOOM_RATE : WHEEL_ZOOM_RATE;
      camera.zoomAt(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-dy * rate));
    },
    { passive: false },
  );

  // The right (or middle) button pans, from anywhere on the graph; the
  // left button selects — a drag on empty canvas draws a box (Shift/⌘
  // adds to the selection), and a press that never moves clears it.
  // "Never moves" means less than CLICK_SLOP pixels, whatever the hand's
  // jitter. A right press that never moves is still the right-click
  // menu: macOS fires ``contextmenu`` on the press, before anyone knows
  // whether a drag follows, so the canvas holds the event and replays
  // it on release (``menuAt``).
  const CLICK_SLOP = 3;
  let drag: { x: number; y: number; sx: number; sy: number; id: number; moved: boolean; menuAt: Element | null } | null = null;
  let band: { b: SelectionBand; id: number; sx: number; sy: number; moved: boolean; add: boolean } | null = null;
  let replaying = false;
  host.addEventListener("contextmenu", (e) => {
    if (replaying) return;
    e.preventDefault();
    e.stopPropagation();
  }, true);
  host.addEventListener("pointerdown", (e: PointerEvent) => {
    const t = e.target as Element | null;
    // A drag from an overlay card (expanded tooltip, node menu, raw
    // JSON) is the user SELECTING TEXT, not panning — and the pan's
    // dismissOverlays() would eat the card mid-selection.
    if (t?.closest?.(".history-tooltip, .dag-inspector, .dag-menu-verbs")) return;
    const pans = e.button === 2 || e.button === 1;
    // A left press on a node or a branch name is a click on it.
    if (!pans && t?.closest?.(".history-node, .history-branch-tag")) return;
    camera.dismiss();
    try {
      host.setPointerCapture(e.pointerId);
    } catch {
      /* a pointer that vanished mid-gesture is not an error */
    }
    if (!pans) {
      releaseEditableFocus();
      band = {
        b: new SelectionBand(host, { x: e.clientX, y: e.clientY }),
        id: e.pointerId, sx: e.clientX, sy: e.clientY, moved: false,
        add: e.shiftKey || e.metaKey,
      };
      return;
    }
    drag = {
      x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY,
      id: e.pointerId, moved: false, menuAt: e.button === 2 ? t : null,
    };
    host.classList.add("is-panning");
  });
  host.addEventListener("pointermove", (e: PointerEvent) => {
    if (band && e.pointerId === band.id) {
      if (!band.moved
          && Math.hypot(e.clientX - band.sx, e.clientY - band.sy) < CLICK_SLOP) {
        return;
      }
      band.moved = true;
      band.b.move({ x: e.clientX, y: e.clientY });
      return;
    }
    if (!drag || e.pointerId !== drag.id) return;
    setView(
      _viewTx + (e.clientX - drag.x),
      _viewTy + (e.clientY - drag.y),
      _viewScale,
    );
    drag.x = e.clientX;
    drag.y = e.clientY;
    drag.moved = drag.moved
      || Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) >= CLICK_SLOP;
    camera.moved();
  });
  const endDrag = (e: PointerEvent): void => {
    if (band && e.pointerId === band.id) {
      const { b, moved, add } = band;
      band = null;
      const hits = moved && e.type === "pointerup" ? b.hits() : [];
      b.remove();
      if (hits.length) select(hits, add ? "add" : "replace");
      else if (!add && e.type === "pointerup") clearSelection();
      return;
    }
    if (!drag || e.pointerId !== drag.id) return;
    const { menuAt, moved } = drag;
    drag = null;
    host.classList.remove("is-panning");
    if (menuAt && !moved && e.type === "pointerup") {
      replaying = true;
      menuAt.dispatchEvent(new MouseEvent("contextmenu", {
        bubbles: true, cancelable: true, clientX: e.clientX, clientY: e.clientY, button: 2,
      }));
      replaying = false;
    }
  };
  host.addEventListener("pointerup", endDrag);
  host.addEventListener("pointercancel", endDrag);
}
