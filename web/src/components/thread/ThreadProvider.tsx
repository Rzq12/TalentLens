"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

/**
 * "Pull the thread" — the signature interaction.
 *
 * Any figure can declare the provenance chain that produced it. Hovering or
 * focusing it raises the thread: a fixed-layer SVG polyline drawn backwards
 * through every anchor that contributed, ending at the cited span in the
 * document. Fixed layer, so it escapes every overflow ancestor by construction.
 */

type Point = { x: number; y: number };

type ThreadContext = {
  registerAnchor: (id: string, el: HTMLElement | null) => void;
  pull: (chain: string[], opts?: { locked?: boolean }) => void;
  release: () => void;
  activeChain: string[];
  locked: boolean;
};

const Ctx = createContext<ThreadContext | null>(null);

export function useThread() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useThread must be used inside ThreadProvider");
  return ctx;
}

export function ThreadProvider({ children }: { children: React.ReactNode }) {
  const anchors = useRef(new Map<string, HTMLElement>());
  const [activeChain, setActiveChain] = useState<string[]>([]);
  const [locked, setLocked] = useState(false);
  const [points, setPoints] = useState<Point[]>([]);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const registerAnchor = useCallback((id: string, el: HTMLElement | null) => {
    if (el) anchors.current.set(id, el);
    else anchors.current.delete(id);
  }, []);

  const measure = useCallback((chain: string[]) => {
    const next: Point[] = [];
    for (const id of chain) {
      const el = anchors.current.get(id);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      next.push({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
    }
    setPoints(next);
  }, []);

  const pull = useCallback(
    (chain: string[], opts?: { locked?: boolean }) => {
      if (locked && !opts?.locked) return;
      setActiveChain(chain);
      if (opts?.locked) setLocked(true);
      measure(chain);
    },
    [locked, measure],
  );

  const release = useCallback(() => {
    if (locked) return;
    setActiveChain([]);
    setPoints([]);
  }, [locked]);

  // Escape unlocks a pinned thread.
  useEffect(() => {
    if (!locked) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLocked(false);
        setActiveChain([]);
        setPoints([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [locked]);

  // Keep a live thread stitched to its anchors while the page moves.
  useEffect(() => {
    if (activeChain.length === 0) return;
    let frame = 0;
    const remeasure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => measure(activeChain));
    };
    window.addEventListener("scroll", remeasure, true);
    window.addEventListener("resize", remeasure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", remeasure, true);
      window.removeEventListener("resize", remeasure);
    };
  }, [activeChain, measure]);

  const value = useMemo(
    () => ({ registerAnchor, pull, release, activeChain, locked }),
    [registerAnchor, pull, release, activeChain, locked],
  );

  const d =
    points.length > 1
      ? points
          .map(
            (p, i) =>
              `${i === 0 ? "M" : "L"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`,
          )
          .join(" ")
      : "";

  return (
    <Ctx.Provider value={value}>
      {children}
      <svg
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-40 h-full w-full"
        style={{
          opacity: d ? 1 : 0,
          transition: "opacity 200ms var(--ease-out-expo)",
        }}
      >
        {d ? (
          <>
            <path
              d={d}
              fill="none"
              stroke="var(--color-leaf)"
              strokeWidth={4.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={0.85}
            />
            <path
              d={d}
              fill="none"
              stroke="var(--color-stamp)"
              strokeWidth={1.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray={locked ? undefined : "5 4"}
              style={
                reduced
                  ? undefined
                  : {
                      transition: "stroke-dasharray 200ms var(--ease-out-expo)",
                    }
              }
            />
            {points.map((p, i) => (
              <circle
                key={i}
                cx={p.x}
                cy={p.y}
                r={i === points.length - 1 ? 4 : 2.5}
                fill={
                  i === points.length - 1
                    ? "var(--color-stamp)"
                    : "var(--color-leaf)"
                }
                stroke="var(--color-stamp)"
                strokeWidth={1.5}
              />
            ))}
          </>
        ) : null}
      </svg>
    </Ctx.Provider>
  );
}

/** Marks an element as a point the thread can pass through. */
export function ThreadAnchor({
  id,
  children,
  className = "",
  as: As = "span",
}: {
  id: string;
  children?: React.ReactNode;
  className?: string;
  as?: "span" | "div" | "td" | "mark";
}) {
  const { registerAnchor } = useThread();
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    registerAnchor(id, ref.current);
    return () => registerAnchor(id, null);
  }, [id, registerAnchor]);

  return (
    <As ref={ref as never} data-thread-anchor={id} className={className}>
      {children}
    </As>
  );
}

/** A figure that can be pulled: raises its own provenance chain. */
export function Pullable({
  chain,
  children,
  className = "",
  label,
}: {
  chain: string[];
  children: React.ReactNode;
  className?: string;
  label: string;
}) {
  const { pull, release, activeChain, locked } = useThread();
  const isActive = activeChain.length > 0 && activeChain[0] === chain[0];

  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={isActive && locked}
      onMouseEnter={() => pull(chain)}
      onMouseLeave={release}
      onFocus={() => pull(chain)}
      onBlur={release}
      onClick={() =>
        isActive && locked ? undefined : pull(chain, { locked: true })
      }
      className={`group/pull cursor-pointer rounded-sm text-left transition-colors duration-150 ease-out hover:bg-stamp-wash aria-pressed:bg-stamp-wash ${className}`}
    >
      {children}
    </button>
  );
}
