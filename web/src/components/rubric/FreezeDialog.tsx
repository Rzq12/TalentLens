"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/Button";
import { Seal } from "@/components/ui/Seal";
import type { Requirement } from "@/lib/demo";

/**
 * Sealing is irreversible, so this is one of the few places a modal is honest:
 * the task needs protected focus and must interrupt. Native <dialog> so the
 * overlay escapes every overflow ancestor and gets the platform focus trap.
 *
 * The body is a test strip — exactly what will be frozen, developed in place.
 */
export function FreezeDialog({
  open,
  onClose,
  rows,
  total,
}: {
  open: boolean;
  onClose: () => void;
  rows: Requirement[];
  total: number;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [typed, setTyped] = useState("");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
    if (open) setTyped("");
  }, [open]);

  const confirmed = typed.trim().toUpperCase() === "SEAL";

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      aria-labelledby="freeze-title"
      className="m-auto w-[min(46rem,calc(100vw-2rem))] rounded-sm border-2 border-rule-section bg-leaf p-0 text-ink backdrop:bg-ink/60"
    >
      <div className="flex items-start justify-between gap-4 border-b-2 border-rule-section px-6 py-4">
        <div>
          <p className="stamp-label">Irreversible action</p>
          <h2
            id="freeze-title"
            className="mt-1 text-2xl font-semibold track-tight"
          >
            Seal rubric REQ-8992 as v5
          </h2>
        </div>
        <Seal tone="broken" glyph="alert">
          No undo
        </Seal>
      </div>

      <div className="max-h-[52vh] overflow-y-auto px-6 py-4">
        <p className="max-w-[70ch] text-sm text-ink-2">
          Once sealed, this rubric can never be edited. Every score produced
          from it will carry{" "}
          <span className="font-mono text-xs text-ink">rubric_version=v5</span>,
          and any later change must be published as v6, leaving v5 permanently
          reproducible. Runs already in flight continue against the version they
          started with.
        </p>

        <div className="mt-4 border border-rule-entry">
          <div className="flex items-center justify-between border-b border-rule-entry bg-register px-3 py-1.5">
            <span className="stamp-label">Test strip · what gets frozen</span>
            <span className="font-mono text-2xs tabular-nums text-ink-2">
              {total}% weighted
            </span>
          </div>
          <ol className="divide-y divide-rule-hair">
            {rows.map((r, i) => (
              <li key={r.id} className="flex items-baseline gap-3 px-3 py-2">
                <span className="w-6 shrink-0 font-mono text-2xs tabular-nums text-ink-3">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="min-w-0 flex-1 text-sm text-ink">
                  {r.text || (
                    <em className="text-ink-3">
                      Empty requirement — will be dropped
                    </em>
                  )}
                </span>
                {r.mustHave ? (
                  <span className="shrink-0 font-narrow text-2xs font-semibold uppercase track-stamp text-seal">
                    Must have
                  </span>
                ) : null}
                <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums text-ink">
                  {r.weight}%
                </span>
              </li>
            ))}
          </ol>
        </div>

        <label className="mt-4 block">
          <span className="stamp-label">
            Type SEAL to confirm you understand this cannot be undone
          </span>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            className="mt-1 w-48 rounded-sm border border-rule-entry bg-paper px-2.5 py-[7px] font-mono text-sm uppercase track-stamp text-ink transition-colors duration-150 ease-out hover:border-ink-3 focus:border-stamp focus:outline-none"
          />
        </label>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-rule-entry px-6 py-3">
        <p className="flex items-center gap-1.5 text-xs text-ink-3">
          <Icon name="clock" size={13} />
          Sealed by A. Wijaya · recorded to the audit chain
        </p>
        <div className="flex gap-2">
          <Button variant="quiet" onClick={onClose}>
            Keep editing
          </Button>
          <Button
            variant="stamp"
            icon="seal"
            disabled={!confirmed}
            onClick={onClose}
          >
            Seal as v5
          </Button>
        </div>
      </div>
    </dialog>
  );
}
