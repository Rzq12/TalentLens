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
import { REQUIREMENTS, type Requirement } from "@/lib/demo";
import { FreezeDialog } from "@/components/rubric/FreezeDialog";

/**
 * Rubric authoring. Approving is a point of no return: the seal is irreversible,
 * so the weight total must balance and the confirmation shows a test strip of
 * exactly what will be frozen.
 */
export function RubricEditor() {
  const [rows, setRows] = useState<Requirement[]>(REQUIREMENTS);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [freezing, setFreezing] = useState(false);
  const liveRegion = useRef<HTMLParagraphElement>(null);

  const total = useMemo(() => rows.reduce((s, r) => s + r.weight, 0), [rows]);
  const balanced = total === 100;
  const mustHaves = rows.filter((r) => r.mustHave).length;

  const patch = (id: string, next: Partial<Requirement>) =>
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...next } : r)));

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

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-rule-entry bg-leaf px-5 py-3 md:px-8">
        <SelectField
          label="Template base"
          defaultValue="fe-senior"
          className="w-64"
        >
          <option value="fe-senior">Frontend engineering · senior</option>
          <option value="fe-mid">Frontend engineering · mid</option>
          <option value="blank">Blank rubric</option>
        </SelectField>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ruled" icon="sheet">
            Save draft
          </Button>
          <Button
            variant="stamp"
            icon="seal"
            disabled={!balanced}
            title={
              balanced
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
              key={r.id}
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
                broken={r.status === "draft"}
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
                      defaultValue={r.text}
                      rows={2}
                      aria-label={`Requirement text for ${r.id}`}
                      className="w-full resize-y rounded-sm border border-transparent bg-transparent px-1 py-0.5 text-sm text-ink transition-colors duration-150 ease-out hover:border-rule-hair focus:border-stamp focus:bg-paper focus:outline-none"
                    />
                    <div className="px-1 font-mono text-2xs text-ink-3">
                      {r.id}
                    </div>
                  </div>
                </div>
              </Td>
              <Td align="center">
                <Toggle
                  checked={r.mustHave}
                  onChange={(v) => patch(r.id, { mustHave: v })}
                  label={`Mark ${r.id} as must-have`}
                />
                <div className="mt-1 font-narrow text-2xs uppercase track-stamp text-ink-3">
                  {r.mustHave ? "Required" : "Weighted"}
                </div>
              </Td>
              <Td align="right">
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={r.weight}
                  aria-label={`Weight for ${r.id}`}
                  onChange={(e) =>
                    patch(r.id, { weight: Number(e.target.value) || 0 })
                  }
                  className="w-16 rounded-sm border border-rule-entry bg-leaf px-2 py-1 text-right font-mono text-sm tabular-nums text-ink transition-colors duration-150 ease-out hover:border-ink-3 focus:border-stamp focus:outline-none"
                />
              </Td>
              <Td align="right" className="font-mono tabular-nums text-ink-2">
                {r.minYears ?? "—"}
              </Td>
              <Td>
                <Seal tone={r.status === "active" ? "intact" : "draft"}>
                  {r.status === "active" ? "In rubric" : "Draft only"}
                </Seal>
              </Td>
              <Td align="right">
                <div className="flex justify-end gap-1">
                  <IconButton
                    label={`Move ${r.id} up`}
                    icon="chevron-left"
                    className="rotate-90"
                    disabled={i === 0}
                    onClick={() => move(i, i - 1)}
                  />
                  <IconButton
                    label={`Move ${r.id} down`}
                    icon="chevron-right"
                    className="rotate-90"
                    disabled={i === rows.length - 1}
                    onClick={() => move(i, i + 1)}
                  />
                  <IconButton
                    label={`Remove ${r.id}`}
                    icon="trash"
                    tone="alarm"
                    onClick={() =>
                      setRows((p) => p.filter((x) => x.id !== r.id))
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
                id: `REQ-8992-${String(p.length + 1).padStart(2, "0")}`,
                text: "",
                mustHave: false,
                weight: 0,
                minYears: null,
                status: "draft",
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

      <FreezeDialog
        open={freezing}
        onClose={() => setFreezing(false)}
        rows={rows}
        total={total}
      />
    </>
  );
}
