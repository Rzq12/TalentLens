"use client";

import { useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Button, IconButton } from "@/components/ui/Button";
import { Seal } from "@/components/ui/Seal";
import { SelectField, Toggle } from "@/components/ui/Field";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  GutterCell,
} from "@/components/ledger/Ledger";
import { useApproveRubric } from "@/lib/hooks";
import type { RubricResponse, RequirementRow } from "@/lib/api";

interface Props {
  rubric: RubricResponse | null;
  loading: boolean;
  jobId?: string;
}

/**
 * RubricEditorAPI — loads real requirement rows from the API.
 * Approving is a point of no return: the seal is irreversible,
 * so the weight total must balance and the confirmation shows a test strip of
 * exactly what will be frozen.
 */
export function RubricEditorAPI({ rubric, loading, jobId }: Props) {
  const [rows, setRows] = useState<RequirementRow[]>(
    rubric?.requirements ?? [],
  );
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [freezing, setFreezing] = useState(false);
  const liveRegion = useRef<HTMLParagraphElement>(null);
  const { approve, loading: approving, error: approveError } = useApproveRubric();

  // Keep rows in sync when rubric loads
  useMemo(() => {
    if (rubric?.requirements) {
      setRows(rubric.requirements);
    }
  }, [rubric?.rubric_id]);

  const total = useMemo(() => rows.reduce((s, r) => s + r.weight, 0), [rows]);
  const balanced = total === 100;
  const mustHaves = rows.filter((r) => r.must_have).length;

  const patch = (id: string, next: Partial<RequirementRow>) =>
    setRows((prev) =>
      prev.map((r) => (r.requirement_id === id ? { ...r, ...next } : r)),
    );

  const move = (from: number, to: number) => {
    if (to < 0 || to >= rows.length || from === to) return;
    setRows((prev) => {
      const copy = [...prev];
      const [item] = copy.splice(from, 1);
      copy.splice(to, 0, item);
      return copy;
    });
    if (liveRegion.current) {
      liveRegion.current.textContent = `Requirement moved to position ${to + 1} of ${rows.length}.`;
    }
  };

  const handleApprove = async () => {
    if (!rubric || !balanced) return;
    try {
      await approve(rubric.rubric_id);
      setFreezing(false);
    } catch {
      // error shown inline
    }
  };

  if (loading) {
    return (
      <div className="bg-leaf px-5 py-16 text-center md:px-8">
        <div className="text-ink-3">Loading rubric...</div>
      </div>
    );
  }

  if (!rubric && !loading) {
    return (
      <div className="bg-leaf px-5 py-16 text-center md:px-8">
        <Icon name="sheet" size={34} className="mx-auto text-ink-3" />
        <h2 className="mt-3 text-lg font-semibold track-tight text-ink">
          No rubric found
        </h2>
        <p className="mx-auto mt-1 max-w-[52ch] text-sm text-ink-2">
          {jobId
            ? "No rubric exists for this job. Create one to start screening."
            : "Select a job to view its rubric, or navigate here from a job page."}
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-rule-entry bg-leaf px-5 py-3 md:px-8">
        <SelectField
          label="Template base"
          defaultValue="current"
          className="w-64"
        >
          <option value="current">
            {rubric?.job_id ?? "Current rubric"}
          </option>
        </SelectField>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ruled" icon="sheet">
            Save draft
          </Button>
          <Button
            variant="stamp"
            icon="seal"
            disabled={!balanced || rubric?.status === "approved" || approving}
            title={
              rubric?.status === "approved"
                ? "This rubric has already been sealed"
                : balanced
                  ? undefined
                  : `Weights total ${total}%. They must total exactly 100% before the rubric can be sealed.`
            }
            onClick={() => setFreezing(true)}
          >
            Approve &amp; seal
          </Button>
        </div>
      </div>

      {/* Weight balance — the gate, stated as a fact not a toast. */}
      <div
        className={`flex flex-wrap items-center gap-x-6 gap-y-2 border-b-2 px-5 py-3 md:px-8 ${
          balanced
            ? "border-rule-section bg-stamp-wash"
            : "border-seal bg-seal-wash"
        }`}
      >
        <span className="flex items-center gap-2">
          <Icon
            name={balanced ? "check" : "alert"}
            size={16}
            className={balanced ? "text-stamp" : "text-seal"}
          />
          <span className="stamp-label">Weight balance</span>
        </span>
        <span
          className={`font-mono text-xl tabular-nums ${balanced ? "text-stamp" : "text-seal"}`}
        >
          {total}%
        </span>
        <span
          className="flex h-3 w-48 border border-current text-ink"
          aria-hidden="true"
        >
          <span
            className={balanced ? "bg-stamp" : "bg-seal"}
            style={{ width: `${Math.min(total, 100)}%` }}
          />
        </span>
        <p className={`text-xs ${balanced ? "text-ink-2" : "text-seal"}`}>
          {balanced
            ? "Balanced. Sealing this rubric freezes it and stamps its version onto every score produced from it."
            : `Weights must total exactly 100% before the rubric can be sealed. Currently ${
                total > 100 ? `${total - 100}% over` : `${100 - total}% short`
              }.`}
        </p>
        <span className="ml-auto stamp-label">
          {mustHaves} must-have requirements
        </span>
      </div>

      <Ledger className="bg-leaf">
        <LedgerHead>
          <Th width="4rem" align="center">
            Seq
          </Th>
          <Th>Requirement text · the sentence the model is asked to verify</Th>
          <Th width="7rem" align="center">
            Must have
          </Th>
          <Th width="7rem" align="right">
            Weight
          </Th>
          <Th width="7rem" align="right">
            Min yrs
          </Th>
          <Th width="8rem">State</Th>
          <Th width="7rem" align="right">
            Order
          </Th>
        </LedgerHead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={r.requirement_id}
              draggable
              onDragStart={() => setDragIndex(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragIndex !== null) move(dragIndex, i);
                setDragIndex(null);
              }}
              className={`border-b border-rule-hair transition-colors duration-150 ease-out hover:bg-recess/60 ${
                dragIndex === i ? "bg-stamp-wash" : ""
              }`}
            >
              <GutterCell
                ordinal={i + 1}
                first={i === 0}
                last={i === rows.length - 1}
                broken={!r.weight}
              />
              <Td>
                <div className="flex items-start gap-2">
                  <Icon
                    name="grip"
                    size={14}
                    className="mt-1 shrink-0 cursor-grab text-ink-3"
                  />
                  <div className="min-w-0">
                    <textarea
                      defaultValue={r.label}
                      rows={2}
                      aria-label={`Requirement text for ${r.requirement_id}`}
                      className="w-full resize-y rounded-sm border border-transparent bg-transparent px-1 py-0.5 text-sm text-ink transition-colors duration-150 ease-out hover:border-rule-hair focus:border-stamp focus:bg-paper focus:outline-none"
                    />
                    {r.description ? (
                      <p className="px-1 text-xs text-ink-2">{r.description}</p>
                    ) : null}
                    <div className="px-1 font-mono text-2xs text-ink-3">
                      {r.requirement_id}
                    </div>
                  </div>
                </div>
              </Td>
              <Td align="center">
                <Toggle
                  checked={r.must_have}
                  onChange={(v) => patch(r.requirement_id, { must_have: v })}
                  label={`Mark ${r.requirement_id} as must-have`}
                />
                <div className="mt-1 font-narrow text-2xs uppercase track-stamp text-ink-3">
                  {r.must_have ? "Required" : "Weighted"}
                </div>
              </Td>
              <Td align="right">
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={r.weight}
                  aria-label={`Weight for ${r.requirement_id}`}
                  onChange={(e) =>
                    patch(r.requirement_id, {
                      weight: Number(e.target.value) || 0,
                    })
                  }
                  className="w-16 rounded-sm border border-rule-entry bg-leaf px-2 py-1 text-right font-mono text-sm tabular-nums text-ink transition-colors duration-150 ease-out hover:border-ink-3 focus:border-stamp focus:outline-none"
                />
              </Td>
              <Td align="right" className="font-mono tabular-nums text-ink-2">
                {r.min_years ?? "—"}
              </Td>
              <Td>
                <Seal tone={r.verdict ? "intact" : "neutral"}>
                  {r.verdict ? "Has verdict" : "In rubric"}
                </Seal>
              </Td>
              <Td align="right">
                <div className="flex justify-end gap-1">
                  <IconButton
                    label={`Move ${r.requirement_id} up`}
                    icon="chevron-left"
                    className="rotate-90"
                    disabled={i === 0}
                    onClick={() => move(i, i - 1)}
                  />
                  <IconButton
                    label={`Move ${r.requirement_id} down`}
                    icon="chevron-right"
                    className="rotate-90"
                    disabled={i === rows.length - 1}
                    onClick={() => move(i, i + 1)}
                  />
                  <IconButton
                    label={`Remove ${r.requirement_id}`}
                    icon="trash"
                    tone="alarm"
                    onClick={() =>
                      setRows((p) =>
                        p.filter((x) => x.requirement_id !== r.requirement_id),
                      )
                    }
                  />
                </div>
              </Td>
            </tr>
          ))}
        </tbody>
      </Ledger>

      <p
        ref={liveRegion}
        role="status"
        aria-live="polite"
        className="sr-only"
      />

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule-entry bg-leaf px-5 py-3 md:px-8">
        <Button
          variant="ruled"
          icon="plus"
          onClick={() =>
            setRows((p) => [
              ...p,
              {
                requirement_id: `REQ-new-${Date.now()}`,
                label: "",
                must_have: false,
                weight: 0,
                min_years: undefined,
              },
            ])
          }
        >
          Add requirement
        </Button>
        <p className="max-w-[70ch] text-xs text-ink-2">
          Requirements are evaluated one at a time and answered met, partial or
          missing. There is no prompt anywhere in this system that asks a model
          to score a resume out of one hundred — the total is arithmetic over
          these verdicts.
        </p>
      </div>

      {/* Freeze confirmation */}
      {freezing ? (
        <dialog
          open
          aria-labelledby="freeze-title"
          className="fixed inset-0 z-50 m-auto h-fit w-[min(46rem,calc(100vw-2rem))] rounded-sm border-2 border-rule-section bg-leaf p-0 text-ink"
        >
          <div
            className="fixed inset-0 bg-ink/60"
            onClick={() => setFreezing(false)}
          />
          <div className="relative">
            <div className="flex items-start justify-between gap-4 border-b-2 border-rule-section px-6 py-4">
              <div>
                <p className="stamp-label">Irreversible action</p>
                <h2
                  id="freeze-title"
                  className="mt-1 text-2xl font-semibold track-tight"
                >
                  Seal rubric {rubric?.rubric_id} as {rubric?.version}
                </h2>
              </div>
              <Seal tone="broken" glyph="alert">
                No undo
              </Seal>
            </div>

            <div className="max-h-[52vh] overflow-y-auto px-6 py-4">
              <p className="max-w-[70ch] text-sm text-ink-2">
                Once sealed, this rubric can never be edited. Every score
                produced from it will carry{" "}
                <span className="font-mono text-xs text-ink">
                  rubric_version={rubric?.version}
                </span>
                .
              </p>

              <div className="mt-4 border border-rule-entry">
                <div className="flex items-center justify-between border-b border-rule-entry bg-register px-3 py-1.5">
                  <span className="stamp-label">
                    Test strip · what gets frozen
                  </span>
                  <span className="font-mono text-2xs tabular-nums text-ink-2">
                    {total}% weighted
                  </span>
                </div>
                <ol className="divide-y divide-rule-hair">
                  {rows.map((r, i) => (
                    <li
                      key={r.requirement_id}
                      className="flex items-baseline gap-3 px-3 py-2"
                    >
                      <span className="w-6 shrink-0 font-mono text-2xs tabular-nums text-ink-3">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="min-w-0 flex-1 text-sm text-ink">
                        {r.label || (
                          <em className="text-ink-3">
                            Empty requirement — will be dropped
                          </em>
                        )}
                      </span>
                      {r.must_have ? (
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
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-rule-entry px-6 py-3">
              <p className="flex items-center gap-1.5 text-xs text-ink-3">
                <Icon name="clock" size={13} />
                Will be recorded permanently in the audit chain
              </p>
              {approveError ? (
                <p className="text-xs text-seal">{approveError.message}</p>
              ) : null}
              <div className="flex gap-2">
                <Button
                  variant="quiet"
                  onClick={() => setFreezing(false)}
                  disabled={approving}
                >
                  Keep editing
                </Button>
                <Button
                  variant="stamp"
                  icon="seal"
                  disabled={approving}
                  onClick={handleApprove}
                >
                  {approving ? "Sealing…" : `Seal as ${rubric?.version}`}
                </Button>
              </div>
            </div>
          </div>
        </dialog>
      ) : null}
    </>
  );
}
