// Hand-offs between the Watch assistant (mounted once in the layout) and the Watches page:
// a proposed spec to open in the Watch editor, and a nudge to reload after a Watch was created.
import type { Place, WatchSpec } from "./api";

export type WatchDraft = { spec: WatchSpec; places: Place[] };

const DRAFT_KEY = "fs:watch-draft";
export const WATCH_DRAFT_EVENT = "fs:watch-draft";
export const WATCHES_CHANGED_EVENT = "fs:watches-changed";

/** Park a draft for the Watch editor (survives the navigation to /watches) and announce it. */
export function offerWatchDraft(draft: WatchDraft) {
  try {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // storage unavailable: nothing to pick up later
  }
  window.dispatchEvent(new CustomEvent(WATCH_DRAFT_EVENT));
}

/** Take (and clear) the parked draft, if any. */
export function takeWatchDraft(): WatchDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(DRAFT_KEY);
    const draft = JSON.parse(raw) as WatchDraft;
    return draft && draft.spec && Array.isArray(draft.places) ? draft : null;
  } catch {
    return null;
  }
}

export const announceWatchesChanged = () => window.dispatchEvent(new CustomEvent(WATCHES_CHANGED_EVENT));
