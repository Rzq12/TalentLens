"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Seal } from "@/components/ui/Seal";
import { RUN } from "@/lib/demo";

/**
 * Waiting is a designed state.
 *
 * The run reads as a commit line: stages already committed are irreversible and
 * ruled solid, the active stage carries the live tick, queued stages are the
 * dashed future. The one number that matters gets monumental scale.
 */
export function RunMonitor() {
  const [reconnected, setReconnected] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setReconnected(false), 6000);
    return () => clearTimeout(t);
  }, []);

  const remaining = RUN.total - RUN.processed;

  return (
    <>
      {reconnected ? (
        <div
          role="status"
          className="flex items-center gap-2 border-b border-rule-entry bg-stamp-wash px-5 py-2 text-xs text-stamp md:px-8"
        >
          <Icon name="thread" size={13} />
          <span className="font-narrow font-semibold uppercase track-stamp">
            Live updates reconnected
          </span>
          <span className="text-ink-2">
            No entries were lost; the register resumed from sequence{" "}
            {RUN.processed}.
          </span>
        </div>
      ) : null}

      <section className="grid grid-cols-1 border-b-2 border-rule-section bg-leaf lg:grid-cols-[22rem_minmax(0,1fr)]">
        {/* The one figure that matters, at monumental scale. */}
        <div className="border-b border-rule-entry px-5 py-6 md:px-8 lg:border-b-0 lg:border-r">
          <div className="stamp-label">Candidates recorded</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="num-monument text-ink">{RUN.processed}</span>
            <span className="font-mono text-lg tabular-nums text-ink-3">
              / {RUN.total}
            </span>
          </div>

          <div
            className="mt-4 flex h-3 w-full border border-rule-section"
            role="progressbar"
            aria-valuenow={RUN.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Run progress"
          >
            <span
              className="bg-stamp transition-[width] duration-200 ease-out"
              style={{ width: `${RUN.percent}%` }}
            />
            <span
              className="developing flex-1"
              style={{
                background:
                  "repeating-linear-gradient(135deg, var(--color-rule-hair) 0 4px, transparent 4px 8px)",
              }}
              aria-hidden="true"
            />
          </div>

          <dl className="mt-4 divide-y divide-rule-hair border-y border-rule-hair">
            <div className="flex items-baseline justify-between py-1.5">
              <dt className="stamp-label">Committed</dt>
              <dd className="font-mono text-xs tabular-nums text-ink">
                {RUN.percent}%
              </dd>
            </div>
            <div className="flex items-baseline justify-between py-1.5">
              <dt className="stamp-label">Remaining</dt>
              <dd className="font-mono text-xs tabular-nums text-ink">
                {remaining}
              </dd>
            </div>
            <div className="flex items-baseline justify-between py-1.5">
              <dt className="stamp-label">Estimated close</dt>
              <dd className="font-mono text-xs tabular-nums text-ink">
                ~{RUN.etaMinutes} min
              </dd>
            </div>
          </dl>

          <p className="mt-3 text-xs text-ink-2">
            Committed entries are written to the chain as they complete. Pausing
            stops new work; it does not roll back anything already recorded.
          </p>
        </div>

        {/* The commit line. */}
        <ol className="px-5 py-5 md:px-8">
          {RUN.stages.map((s, i) => {
            const last = i === RUN.stages.length - 1;
            return (
              <li key={s.n} className="relative flex gap-4 pb-5 last:pb-0">
                {!last ? (
                  <span
                    aria-hidden="true"
                    className={`absolute left-[15px] top-8 bottom-0 w-[1px] ${
                      s.state === "done"
                        ? "bg-stamp"
                        : s.state === "active"
                          ? "bg-[repeating-linear-gradient(to_bottom,var(--color-stamp)_0_3px,transparent_3px_7px)]"
                          : "bg-rule-hair"
                    }`}
                  />
                ) : null}
                <span
                  className={`relative z-[1] flex h-8 w-8 shrink-0 items-center justify-center border font-mono text-xs tabular-nums ${
                    s.state === "done"
                      ? "border-stamp bg-stamp text-leaf"
                      : s.state === "active"
                        ? "border-stamp bg-stamp-wash text-stamp"
                        : "border-dashed border-rule-entry bg-transparent text-ink-3"
                  }`}
                >
                  {s.state === "done" ? <Icon name="check" size={15} /> : s.n}
                </span>
                <div className="min-w-0 flex-1 pt-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3
                      className={`text-base font-semibold track-tight ${
                        s.state === "queued" ? "text-ink-3" : "text-ink"
                      }`}
                    >
                      {s.label}
                    </h3>
                    <Seal
                      tone={
                        s.state === "done"
                          ? "intact"
                          : s.state === "active"
                            ? "pending"
                            : "neutral"
                      }
                    >
                      {s.state === "done"
                        ? "Committed"
                        : s.state === "active"
                          ? "In progress"
                          : "Queued"}
                    </Seal>
                  </div>
                  <p className="mt-0.5 text-sm text-ink-2">{s.detail}</p>
                  {s.state === "active" ? (
                    <div className="mt-2 flex gap-1" aria-hidden="true">
                      {Array.from({ length: 24 }).map((_, k) => (
                        <span
                          key={k}
                          className={`h-4 w-[3px] ${
                            k < 15 ? "bg-stamp" : "developing bg-rule-hair"
                          }`}
                          style={
                            k >= 15
                              ? { animationDelay: `${(k - 15) * 90}ms` }
                              : undefined
                          }
                        />
                      ))}
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
      </section>
    </>
  );
}
