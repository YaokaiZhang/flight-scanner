"use client";

// Watch assistant: a hand-drawn robot at the bottom-right of every page that opens a side chat.
// The robot can be dragged anywhere on screen; where it was left is remembered in this browser.
// The assistant answers in plain text and may propose Watches, each drawn as a ruled "watch
// sheet" that can be created with one click or opened in the Watch editor.

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent } from "react";
import { api, ApiError, placeKey, type ChatTurn, type Place, type PlaceRef, type Proposal, type WatchSpec } from "@/lib/api";
import { formatDate, formatEur } from "@/lib/format";
import { announceWatchesChanged, offerWatchDraft } from "@/lib/watchDraft";
import { Icon } from "./PlacePicker";
import { describePreset } from "./TripPatternFields";
import { problem } from "./WatchEditor";

type SheetState = "open" | "created" | "dismissed";
type Sheet = Proposal & { state: SheetState; problem?: string };
type Entry =
  | { role: "owner"; text: string }
  | { role: "assistant"; text: string; proposals: Sheet[] };
type Saved = { chatId: number | null; log: Entry[] };

const STORE_KEY = "fs:watch-assistant";
const SPOT_KEY = "fs:robot-spot";
const DRAG_SLOP = 4; // px of travel before a press becomes a drag rather than a click
const EDGE = 8; // px the robot keeps from the viewport edges
const STARTERS = [
  "Suggest a Watch from the Deals you've seen",
  "Long weekends somewhere warm this winter",
  "Cheapest way to visit family at Christmas",
];
const OFF_NOTE = "The assistant is off. Set FS_WATCH_AGENT=claude and ANTHROPIC_API_KEY in .env.";

function load(): Saved {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    const saved = raw ? (JSON.parse(raw) as Saved) : null;
    if (saved && Array.isArray(saved.log)) return saved;
  } catch {
    // unreadable or unavailable: start fresh
  }
  return { chatId: null, log: [] };
}

function save(s: Saved) {
  try {
    if (s.chatId === null && s.log.length === 0) sessionStorage.removeItem(STORE_KEY);
    else sessionStorage.setItem(STORE_KEY, JSON.stringify(s));
  } catch {
    // storage full or blocked: the chat still works for this page view
  }
}

/** Where the robot sits, as distances from the viewport's right and bottom edges. */
type Spot = { right: number; bottom: number };

function loadSpot(): Spot | null {
  try {
    const s = JSON.parse(localStorage.getItem(SPOT_KEY) ?? "null");
    return s && typeof s.right === "number" && typeof s.bottom === "number" ? s : null;
  } catch {
    return null;
  }
}

function saveSpot(s: Spot) {
  try {
    localStorage.setItem(SPOT_KEY, JSON.stringify(s));
  } catch {
    // storage unavailable: the robot just returns to its corner next time
  }
}

function clampSpot(s: Spot, size: number): Spot {
  const { clientWidth: w, clientHeight: h } = document.documentElement;
  return {
    right: Math.round(Math.min(Math.max(s.right, EDGE), w - size - EDGE)),
    bottom: Math.round(Math.min(Math.max(s.bottom, EDGE), h - size - EDGE)),
  };
}

function failure(err: unknown): string {
  if (!(err instanceof ApiError)) return "Could not reach the assistant (network).";
  const detail = (err.detail as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  return `The assistant could not answer (${err.status}).`;
}

/** The robot, in the felt-tip hand of the "fs" logo: ink strokes, a graphite antenna lead to an
 *  ink dot, and a dashed flight path underneath that ends in a small plane. */
function RobotMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <path d="M5 57 Q31 64 59 52" stroke="var(--graphite)" strokeWidth="0.8" strokeDasharray="1.5 3" strokeLinecap="round" />
      <path d="M6 0 C6 -0.7 5.2 -1 4.4 -1 L1.4 -1 L-1.6 -5.6 L-3 -5.6 L-1.2 -1 L-4 -1 L-5.4 -2.8 L-6.4 -2.8 L-5.6 0 L-6.4 2.8 L-5.4 2.8 L-4 1 L-1.2 1 L-3 5.6 L-1.6 5.6 L1.4 1 L4.4 1 C5.2 1 6 0.7 6 0 Z" transform="translate(57 52.8) rotate(-23) scale(0.8)" fill="var(--ink)" />
      <path
        d="M17.5 27 C17 22 19 19.8 24 19.6 L40.5 19 C45.5 18.8 47.6 21 47.6 25.6 L48 41 C48.2 46 46 48.2 41.2 48.3 L24 48.6 C19.4 48.7 17.4 46.4 17.3 42 Z"
        stroke="var(--ink)"
        strokeWidth="4.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M11.5 29.5 C11.2 32 11.2 35 11.6 37.5" stroke="var(--ink)" strokeWidth="3.6" strokeLinecap="round" />
      <path d="M53.6 29 C54 31.6 54 34.4 53.7 37" stroke="var(--ink)" strokeWidth="3.6" strokeLinecap="round" />
      <circle className="robot-eye" cx="27" cy="31.6" r="3" fill="var(--ink)" />
      <circle className="robot-eye" cx="38.6" cy="31.2" r="3" fill="var(--ink)" />
      <path d="M27.4 39.6 C30 42.2 35 42.3 38 39.4" stroke="var(--ink)" strokeWidth="2.6" strokeLinecap="round" />
      <path d="M32.6 19.2 C32.2 15 33.6 11.6 36.4 8.6" stroke="var(--graphite)" strokeWidth="1.2" strokeLinecap="round" />
      <circle className="robot-antenna" cx="38" cy="7.2" r="2.4" fill="var(--ink)" />
    </svg>
  );
}

function placeList(spec: WatchSpec, places: Place[], side: "origins" | "destinations") {
  const names = new Map(places.map((p) => [placeKey(p), p.name]));
  const name = (r: PlaceRef) => names.get(placeKey(r)) ?? r.code;
  const inc = spec[side].include.map(name).join(", ");
  const exc = (spec[side].exclude ?? []).map(name);
  return exc.length ? `${inc} − ${exc.join(", ")}` : inc;
}

const count = (n: number, one: string) => `${n.toLocaleString("en-GB")} ${n === 1 ? one : `${one}s`}`;

function WatchSheet({
  sheet,
  onCreate,
  onEdit,
  onDismiss,
}: {
  sheet: Sheet;
  onCreate: () => Promise<void>;
  onEdit: () => void;
  onDismiss: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const titleId = useId();
  const { spec, trip, resolved } = sheet;
  const created = sheet.state === "created";
  const span =
    trip.departure_start === trip.departure_end
      ? formatDate(trip.departure_start)
      : `${formatDate(trip.departure_start)} – ${formatDate(trip.departure_end)}`;
  const threshold = spec.price_threshold
    ? `${formatEur(spec.price_threshold.amount_eur)}${spec.price_threshold.basis === "per_adult" ? " /adult" : " total"}`
    : "none";

  return (
    <article className={`wa-sheet${created ? " created" : ""}`} aria-labelledby={titleId}>
      <h3 className="wa-sheet-name" id={titleId}>{spec.name}</h3>
      <p className="wa-sheet-route">
        {placeList(spec, sheet.places, "origins")}
        <span className="arrow">→</span>
        {placeList(spec, sheet.places, "destinations")}
      </p>
      <dl className="wa-facts">
        <dt>Trip</dt>
        <dd>
          {describePreset(spec.trip_pattern)}
          <div className="sub">
            departs <b>{span}</b> · {count(trip.trip_count, "trip")}
            {trip.expired ? " · expired" : ""}
          </div>
        </dd>
        <dt>Airports</dt>
        <dd>{count(resolved.origins, "airport")} → {count(resolved.destinations, "airport")}</dd>
        <dt>Adults</dt>
        <dd>{spec.adults}</dd>
        <dt>Threshold</dt>
        <dd>{threshold}</dd>
      </dl>
      {sheet.reason && <p className="wa-reason">{sheet.reason}</p>}
      {created ? (
        <p className="wa-created" role="status">
          <span className="tag verified">Created</span>
          <Link href="/watches">See it in Watches</Link>
        </p>
      ) : (
        <>
          <div className="actions">
            <button
              className="btn-marker primary"
              type="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await onCreate();
                setBusy(false);
              }}
            >
              {busy ? "Creating" : "Create"}
            </button>
            <button className="btn-marker" type="button" disabled={busy} onClick={onEdit}>
              Edit
            </button>
            <span className="spacer" />
            <button className="btn-marker danger" type="button" disabled={busy} onClick={onDismiss}>
              Dismiss
            </button>
          </div>
          {sheet.problem && <p className="error" role="alert">{sheet.problem}</p>}
        </>
      )}
    </article>
  );
}

export function WatchAssistant() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [chat, setChat] = useState<Saved>({ chatId: null, log: [] });
  const [restored, setRestored] = useState(false);
  const [text, setText] = useState("");
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [spot, setSpot] = useState<Spot | null>(null);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; from: Spot; to: Spot | null } | null>(null);
  const dragged = useRef(false); // swallows the click that ends a drag
  const robotRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const logRef = useRef<HTMLOListElement>(null);
  const returnFocus = useRef(false);
  const generation = useRef(0); // bumped by "New chat" so a late reply to the old chat is dropped
  const titleId = useId();

  // Restore the conversation after a reload (client only, so the server render stays empty).
  useEffect(() => {
    setChat(load());
    setSpot(loadSpot());
    setRestored(true);
  }, []);
  useEffect(() => {
    if (restored) save(chat);
  }, [chat, restored]);

  // Opening checks whether the assistant is configured, and moves focus into the drawer.
  useEffect(() => {
    if (!open) {
      if (returnFocus.current) robotRef.current?.focus();
      returnFocus.current = false;
      return;
    }
    let live = true;
    api.agentStatus().then(
      (s) => live && setEnabled(s.enabled),
      (e) => live && (setEnabled(null), setError(failure(e))),
    );
    (inputRef.current?.disabled ? closeRef.current : inputRef.current)?.focus();
    return () => {
      live = false;
    };
  }, [open]);

  const close = useCallback((refocus = true) => {
    returnFocus.current = refocus;
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) close();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  // Keep the newest entry in view.
  const entries = chat.log.length;
  useEffect(() => {
    const log = logRef.current;
    if (!log) return;
    const last = log.lastElementChild as HTMLElement | null;
    if (waiting || !last) log.scrollTop = log.scrollHeight;
    else last.scrollIntoView({ block: "nearest" });
  }, [entries, waiting, open]);

  async function send(message: string) {
    const body = message.trim();
    if (!body || waiting) return;
    const gen = generation.current;
    setError(null);
    setText("");
    setWaiting(true);
    setChat((c) => ({ ...c, log: [...c.log, { role: "owner", text: body }] }));
    let turn: ChatTurn;
    try {
      try {
        turn = chat.chatId === null ? await api.startChat(body) : await api.continueChat(chat.chatId, body);
      } catch (err) {
        // The server forgot this chat (restart, expiry): carry on in a new one.
        if (!(err instanceof ApiError && err.status === 404 && chat.chatId !== null)) throw err;
        turn = await api.startChat(body);
      }
    } catch (err) {
      if (gen === generation.current) {
        setError(failure(err));
        setWaiting(false);
      }
      return;
    }
    if (gen !== generation.current) return;
    setChat((c) => ({
      chatId: turn.chat_id,
      log: [
        ...c.log,
        { role: "assistant", text: turn.reply, proposals: turn.proposals.map((p) => ({ ...p, state: "open" })) },
      ],
    }));
    setWaiting(false);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  const updateSheet = (id: string, change: Partial<Sheet>) =>
    setChat((c) => ({
      ...c,
      log: c.log.map((e) =>
        e.role === "assistant" && e.proposals.some((p) => p.id === id)
          ? { ...e, proposals: e.proposals.map((p) => (p.id === id ? { ...p, ...change } : p)) }
          : e,
      ),
    }));

  async function create(sheet: Sheet) {
    try {
      await api.createWatch(sheet.spec);
      updateSheet(sheet.id, { state: "created", problem: undefined });
      announceWatchesChanged();
    } catch (err) {
      updateSheet(sheet.id, { problem: problem(err) });
    }
  }

  function edit(sheet: Sheet) {
    offerWatchDraft({ spec: sheet.spec, places: sheet.places });
    close(false); // the Watch editor takes focus
    if (!pathname.startsWith("/watches")) router.push("/watches");
  }

  function newChat() {
    generation.current += 1;
    setChat({ chatId: null, log: [] });
    setWaiting(false);
    setError(null);
    setText("");
    inputRef.current?.focus();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(text);
    }
  }

  function onPointerDown(e: PointerEvent<HTMLButtonElement>) {
    if (e.button !== 0) return;
    const box = e.currentTarget.getBoundingClientRect();
    const { clientWidth: w, clientHeight: h } = document.documentElement;
    drag.current = { x: e.clientX, y: e.clientY, from: { right: w - box.right, bottom: h - box.bottom }, to: null };
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: PointerEvent<HTMLButtonElement>) {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.to && Math.hypot(dx, dy) < DRAG_SLOP) return;
    if (!d.to) setDragging(true);
    d.to = clampSpot({ right: d.from.right - dx, bottom: d.from.bottom - dy }, e.currentTarget.offsetWidth);
    setSpot(d.to);
  }

  function onPointerEnd() {
    const d = drag.current;
    drag.current = null;
    if (!d?.to) return;
    dragged.current = true;
    setDragging(false);
    saveSpot(d.to);
  }

  const off = enabled === false;

  return (
    <>
      <button
        ref={robotRef}
        className="wa-robot"
        type="button"
        aria-label="Watch assistant"
        aria-expanded={open}
        title="Watch assistant (drag to move)"
        data-thinking={waiting || undefined}
        data-dragging={dragging || undefined}
        style={spot ? ({ "--wa-right": `${spot.right}px`, "--wa-bottom": `${spot.bottom}px` } as CSSProperties) : undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
        onClick={() => {
          if (dragged.current) {
            dragged.current = false;
            return;
          }
          if (open) close();
          else setOpen(true);
        }}
      >
        <RobotMark />
      </button>
      {open && (
        <section className="wa-drawer" role="dialog" aria-modal="false" aria-labelledby={titleId}>
          <header className="wa-head">
            <RobotMark className="wa-mark" />
            <h2 id={titleId}>Watch assistant</h2>
            <span className="spacer" />
            <button className="btn-marker" type="button" onClick={newChat}>
              New chat
            </button>
            <button ref={closeRef} className="btn-icon" type="button" aria-label="Close Watch assistant" onClick={() => close()}>
              <Icon name="x" />
            </button>
          </header>

          <div className="wa-body">
            {off && <p className="wa-note">{OFF_NOTE}</p>}
            {chat.log.length === 0 && !waiting ? (
              <div className="wa-empty">
                <p>
                  <strong>Describe a trip, or ask for ideas.</strong>
                  I&rsquo;ll propose Watches you can create with one click.
                </p>
                <ul className="wa-starters">
                  {STARTERS.map((s) => (
                    <li key={s}>
                      <button className="btn-marker" type="button" disabled={off} onClick={() => send(s)}>
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <ol className="wa-log" ref={logRef} role="log" aria-live="polite" aria-label="Conversation">
                {chat.log.map((e, i) =>
                  e.role === "owner" ? (
                    <li key={i} className="wa-msg owner">
                      <span className="wa-who">You</span>
                      <p>{e.text}</p>
                    </li>
                  ) : (
                    <li key={i} className="wa-msg assistant">
                      <span className="wa-who">Assistant</span>
                      <p>{e.text}</p>
                      {e.proposals
                        .filter((p) => p.state !== "dismissed")
                        .map((p) => (
                          <WatchSheet
                            key={p.id}
                            sheet={p}
                            onCreate={() => create(p)}
                            onEdit={() => edit(p)}
                            onDismiss={() => updateSheet(p.id, { state: "dismissed" })}
                          />
                        ))}
                    </li>
                  ),
                )}
                {waiting && (
                  <li className="wa-msg assistant wa-thinking" role="status">
                    <span className="wa-who">Assistant</span>
                    <p>Thinking… this can take up to a minute.</p>
                    <span className="wa-draw" aria-hidden="true" />
                  </li>
                )}
              </ol>
            )}
            {error && <p className="error wa-error" role="alert">{error}</p>}
          </div>

          <form
            className="wa-compose"
            onSubmit={(e) => {
              e.preventDefault();
              send(text);
            }}
          >
            <label className="sr-only" htmlFor={`${titleId}-input`}>Message the Watch assistant</label>
            <textarea
              ref={inputRef}
              id={`${titleId}-input`}
              className="input wa-input"
              rows={2}
              placeholder={off ? "The assistant is off" : "Where do you want to go?"}
              value={text}
              disabled={off}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button className="btn-marker primary" type="submit" disabled={off || waiting || !text.trim()}>
              {waiting ? "Waiting" : "Send"}
            </button>
          </form>
        </section>
      )}
    </>
  );
}
