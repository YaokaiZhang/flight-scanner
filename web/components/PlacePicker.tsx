"use client";

// Place picker: chips for included Places and Exclusions, search-as-you-type, the resolved airport
// count and a lazily loaded Region tree of what the included Places cover.

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { api, placeKey, type Place, type PlaceRef, type PlaceSet, type TreeNode } from "@/lib/api";

const KIND_LABEL: Record<PlaceRef["kind"], string> = {
  airport: "airport",
  city: "city",
  country: "country",
  region: "region",
};

export function Icon({ name }: { name: "x" | "minus" | "plus" | "chev" }) {
  const d = {
    x: "M4 4l8 8M12 4l-8 8",
    minus: "M3.5 8h9",
    plus: "M8 3.5v9M3.5 8h9",
    chev: "M6 3.5L10.5 8 6 12.5",
  }[name];
  return (
    <svg className="icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

type Props = {
  label: string; // "From" / "To"
  value: PlaceSet;
  names: Map<string, Place>;
  onChange: (next: PlaceSet, described?: Place) => void;
};

const same = (a: PlaceRef, b: PlaceRef) => a.kind === b.kind && a.code === b.code;

export function PlacePicker({ label, value, names, onChange }: Props) {
  const inputId = useId();
  const listId = useId();
  const [text, setText] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState<number | null>(null);

  const excluding = /^[-−]/.test(text);
  const query = text.replace(/^[-−]\s*/, "").trim();

  useEffect(() => {
    if (!query) {
      setResults([]);
      return;
    }
    let live = true;
    const t = setTimeout(() => {
      api.searchPlaces(query).then(
        (r) => {
          if (!live) return;
          setResults(r);
          setActive(0);
        },
        () => live && setResults([]),
      );
    }, 120);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [query]);

  const valueKey = JSON.stringify(value);
  useEffect(() => {
    if (value.include.length === 0) {
      setCount(null);
      return;
    }
    let live = true;
    api.resolvePlaces(value).then(
      (r) => live && setCount(r.airport_count),
      () => live && setCount(null),
    );
    return () => {
      live = false;
    };
  }, [valueKey]);

  function add(p: Place, asExclusion: boolean) {
    const ref = { kind: p.kind, code: p.code };
    const side = asExclusion ? "exclude" : "include";
    const other = asExclusion ? "include" : "exclude";
    if (!value[side].some((x) => same(x, ref))) {
      onChange({ ...value, [side]: [...value[side], ref], [other]: value[other].filter((x) => !same(x, ref)) } as PlaceSet, p);
    }
    setText("");
    setResults([]);
  }

  function remove(side: "include" | "exclude", ref: PlaceRef) {
    onChange({ ...value, [side]: value[side].filter((x) => !same(x, ref)) } as PlaceSet);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      const n = results.length;
      if (n) setActive((i) => (i + (e.key === "ArrowDown" ? 1 : n - 1)) % n);
    } else if (e.key === "Enter") {
      if (open && results[active]) {
        e.preventDefault();
        add(results[active], excluding);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const name = (r: PlaceRef) => names.get(placeKey(r))?.name ?? r.code;
  const showList = open && query.length > 0 && results.length > 0;

  return (
    <div className="field place-picker">
      <label className="field-label" htmlFor={inputId}>{label}</label>
      {(value.include.length > 0 || value.exclude.length > 0) && (
        <ul className="chips" aria-label={`${label} Places`}>
          {value.include.map((r) => (
            <li className="chip" key={placeKey(r)}>
              <span className="name">{name(r)}</span>
              <span className="kind">{KIND_LABEL[r.kind]}</span>
              <button type="button" aria-label={`Remove ${name(r)}`} onClick={() => remove("include", r)}>
                <Icon name="x" />
              </button>
            </li>
          ))}
          {value.exclude.map((r) => (
            <li className="chip exclude" key={placeKey(r)}>
              <Icon name="minus" />
              <span className="name">{name(r)}</span>
              <span className="kind">exclude</span>
              <button type="button" aria-label={`Remove exclusion ${name(r)}`} onClick={() => remove("exclude", r)}>
                <Icon name="x" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="combo">
        <input
          id={inputId}
          className="input"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList ? `${listId}-${active}` : undefined}
          autoComplete="off"
          placeholder="Add a Place, or −Place to exclude"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKey}
        />
        {showList && (
          <ul className="options" role="listbox" id={listId} aria-label={`${label} suggestions`}>
            {results.map((p, i) => (
              <li
                key={placeKey(p)}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => add(p, excluding)}
              >
                <span className="opt-name">
                  {excluding && <span className="opt-mode">exclude </span>}
                  {p.name}
                  {p.kind === "airport" && <span className="opt-code"> {p.code}</span>}
                </span>
                <span className="opt-meta">
                  {KIND_LABEL[p.kind]}
                  {p.context ? ` · ${p.context}` : ""}
                  {p.kind !== "airport" ? ` · ${p.airport_count} airports` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <p className="resolved" aria-live="polite">
        {value.include.length === 0 ? (
          "Add at least one Place"
        ) : count === null ? (
          "Resolving"
        ) : (
          <>Resolves to <b>{count.toLocaleString("en-GB")} {count === 1 ? "airport" : "airports"}</b></>
        )}
      </p>
      {value.include.some((r) => r.kind !== "airport") && (
        <details className="tree">
          <summary><Icon name="chev" />Region tree</summary>
          <ul>
            {value.include.map((r) => (
              <TreeItem
                key={placeKey(r)}
                place={r}
                label={name(r)}
                exclude={value.exclude}
                excludedAbove={false}
                root
                onExclude={(p) => add(p, true)}
              />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

/** One node of the Region tree; children load when the node is opened. */
function TreeItem({
  place,
  label,
  node: given,
  exclude,
  excludedAbove,
  root = false,
  onExclude,
}: {
  place: PlaceRef;
  label: string;
  node?: TreeNode;
  exclude: PlaceRef[];
  excludedAbove: boolean;
  root?: boolean;
  onExclude?: (p: Place) => void;
}) {
  const [node, setNode] = useState<TreeNode | null>(given?.children ? given : null);
  const loading = useRef(false);
  const excluded = excludedAbove || exclude.some((x) => same(x, place));
  const meta = given ?? node;

  const detail = meta && (
    <span>
      {meta.via ? ` · via ${meta.via}` : ""}
      {meta.kind !== "airport" ? ` · ${meta.airport_count} airports` : ` · ${meta.code}`}
    </span>
  );
  const excludeButton = !root && onExclude && meta && !excluded && (
    <button type="button" className="tree-exclude" aria-label={`Exclude ${meta.name}`} onClick={() => onExclude(meta)}>
      <Icon name="minus" />
    </button>
  );

  if (place.kind === "airport") {
    return (
      <li className={excluded ? "x" : undefined}>
        {label}{detail}{excludeButton}
      </li>
    );
  }

  function load(open: boolean) {
    if (!open || node || loading.current) return;
    loading.current = true;
    api.placeTree(place, 1).then(setNode, () => (loading.current = false));
  }

  return (
    <li className={excluded ? "x" : undefined}>
      <details onToggle={(e) => load((e.currentTarget as HTMLDetailsElement).open)}>
        <summary>
          <Icon name="chev" />
          {label}
          {detail}
        </summary>
        {node?.children ? (
          <ul>
            {node.children.map((c) => (
              <TreeItem
                key={placeKey(c)}
                place={{ kind: c.kind, code: c.code }}
                label={c.name}
                node={c}
                exclude={exclude}
                excludedAbove={excluded}
                onExclude={onExclude}
              />
            ))}
          </ul>
        ) : (
          <p className="meta">Loading</p>
        )}
      </details>
      {excludeButton}
    </li>
  );
}
