"use client";

import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui/Button";
import { Seal } from "@/components/ui/Seal";
import type { Candidate } from "@/lib/demo";

const MIN_REASON = 40;

/**
 * Breaking a seal needs protected focus and must interrupt — the one other
 * honest modal in this product. The reason is mandatory and is the artefact
 * an auditor reads eighteen months from now.
 */
export function OverrideDialog({
  open,
  onClose,
  candidate,
}: {
  open: boolean;
  onClose: () => void;
  candidate: Candidate;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState<"advance" | "hold">("hold");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
    if (open) setReason("");
  }, [open]);

  const enough = reason.trim().length >= MIN_REASON;

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      aria-labelledby="override-title"
      className="m-auto w-[min(42rem,calc(100vw-2rem))] rounded-sm border-2 border-seal bg-leaf p-0 text-ink backdrop:bg-ink/60"
    >
      <div className="flex items-start justify-between gap-4 border-b-2 border-seal px-6 py-4">
        <div>
          <p className="stamp-label">Breaks the chain of custody</p>
          <h2
            id="override-title"
            className="mt-1 text-2xl font-semibold track-tight"
          >
            Override the assessment for {candidate.name}
          </h2>
        </div>
        <Seal tone="broken">Recorded</Seal>
      </div>

      <div className="px-6 py-4">
        <dl className="grid grid-cols-2 divide-x divide-rule-hair border border-rule-entry">
          <div className="px-4 py-3">
            <dt className="stamp-label">Model reading</dt>
            <dd className="mt-1 font-mono text-xl tabular-nums text-ink">
              {candidate.score}
            </dd>
            <dd className="text-xs text-ink-2">
              {candidate.recommendation === "strong" ? "Strong match" : "Match"}
            </dd>
          </div>
          <div className="px-4 py-3">
            <dt className="stamp-label">Your decision</dt>
            <dd className="mt-1.5 flex gap-2">
              {(["advance", "hold"] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDecision(d)}
                  aria-pressed={decision === d}
                  className={`rounded-sm border px-3 py-1 font-narrow text-2xs font-semibold uppercase track-stamp transition-colors duration-150 ease-out ${
                    decision === d
                      ? "border-stamp bg-stamp text-leaf"
                      : "border-rule-entry bg-paper text-ink-2 hover:border-ink-3"
                  }`}
                >
                  {d === "advance" ? "Advance" : "Hold"}
                </button>
              ))}
            </dd>
          </div>
        </dl>

        <label className="mt-4 block">
          <span className="stamp-label">Written reason · required</span>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={4}
            placeholder="Explain what the model missed or misread, citing the evidence you disagree with."
            className="mt-1 w-full resize-y rounded-sm border border-rule-entry bg-paper px-2.5 py-2 text-sm text-ink transition-colors duration-150 ease-out hover:border-ink-3 focus:border-stamp focus:outline-none"
          />
        </label>
        <p
          className={`mt-1 flex items-center gap-1.5 text-xs ${
            enough ? "text-ink-3" : "text-seal"
          }`}
        >
          <Icon name={enough ? "check" : "alert"} size={12} />
          {enough
            ? "Sufficient. This text is stored verbatim in the audit chain."
            : `At least ${MIN_REASON} characters — currently ${reason.trim().length}.`}
        </p>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-rule-entry px-6 py-3">
        <p className="flex items-center gap-1.5 text-xs text-ink-3">
          <Icon name="clock" size={13} />
          Recorded as A. Wijaya · recruiter
        </p>
        <div className="flex gap-2">
          <Button variant="quiet" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="alarm"
            icon="seal"
            disabled={!enough}
            onClick={onClose}
          >
            Break seal &amp; record
          </Button>
        </div>
      </div>
    </dialog>
  );
}
