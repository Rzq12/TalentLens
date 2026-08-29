"use client";

import { useState } from "react";
import { Icon } from "@/components/Icon";
import { Seal } from "@/components/ui/Seal";
import { Button, IconButton } from "@/components/ui/Button";
import { ThreadAnchor, Pullable } from "@/components/thread/ThreadProvider";
import { RESUME_PAGE_TEXT, type Candidate, type Verdict } from "@/lib/demo";
import { OverrideDialog } from "@/components/evidence/OverrideDialog";

const VERDICT_TONE: Record<Verdict, "intact" | "pending" | "broken"> = {
  met: "intact",
  partial: "pending",
  missing: "broken",
};

const VERDICT_LABEL: Record<Verdict, string> = {
  met: "Met",
  partial: "Partially met",
  missing: "Not found",
};

/**
 * The deep dive. Left: the per-requirement verdicts that composed the total.
 * Right: the document. Pulling a thread on a verdict raises a line that leaves
 * the register, crosses the gutter and terminates on the exact span in the page.
 */
export function EvidencePane({ candidate }: { candidate: Candidate }) {
  const [overriding, setOverriding] = useState(false);
  const [cursor, setCursor] = useState(0);
  const findings = candidate.findings;

  if (!findings.length) {
    return (
      <div className="bg-leaf px-5 py-16 text-center md:px-8">
        <Icon name="sheet" size={34} className="mx-auto text-ink-3" />
        <h2 className="mt-3 text-lg font-semibold track-tight text-ink">
          No evidence recorded yet
        </h2>
        <p className="mx-auto mt-1 max-w-[52ch] text-sm text-ink-2">
          This assessment was ranked but its per-requirement evidence has not
          been accessioned into the register. Re-run the evidence extraction
          stage to populate it.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="grid grid-cols-1 border-t-2 border-rule-section bg-leaf xl:grid-cols-[minmax(0,29rem)_minmax(0,1fr)]">
        {/* Verdict register */}
        <div className="border-b border-rule-entry xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5">
            <h2 className="stamp-label">Requirement verdicts</h2>
            <span className="font-mono text-2xs tabular-nums text-ink-2">
              {findings.length} of 5
            </span>
          </div>

          <div className="flex items-baseline gap-3 border-b-2 border-rule-section px-5 py-4">
            <div>
              <div className="stamp-label">Aggregate</div>
              <div className="num-monument text-ink">{candidate.score}</div>
            </div>
            <p className="max-w-[34ch] text-xs text-ink-2">
              Arithmetic over the verdicts below. No model was ever asked for
              this number.
            </p>
          </div>

          <ol className="divide-y divide-rule-hair">
            {findings.map((f, i) => (
              <li key={f.requirementId} className="relative px-5 py-4">
                <span
                  aria-hidden="true"
                  className={`tick-spine top-0 h-full ${i === 0 ? "top-4" : ""}`}
                  style={{ left: "1.25rem" }}
                  data-broken={f.verdict === "missing" ? "true" : undefined}
                />
                <div className="pl-7">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-2xs tabular-nums text-ink-3">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <Seal tone={VERDICT_TONE[f.verdict]}>
                      {VERDICT_LABEL[f.verdict]}
                    </Seal>
                    <span className="ml-auto font-mono text-2xs tabular-nums text-ink-2">
                      {f.contribution} / {f.weight} pts
                    </span>
                  </div>

                  <h3 className="mt-1.5 text-sm font-medium text-ink">
                    {f.label}
                  </h3>
                  <p className="font-mono text-2xs text-ink-3">
                    {f.requirementId}
                  </p>

                  {f.evidence.length ? (
                    <div className="mt-2 border-l-2 border-rule-entry pl-3">
                      <Pullable
                        chain={[
                          `finding-${f.requirementId}`,
                          `span-${f.evidence[Math.min(cursor, f.evidence.length - 1)].id}`,
                        ]}
                        label={`Pull the thread from ${f.label} to its evidence in the document`}
                        className="w-full text-left"
                      >
                        <ThreadAnchor
                          id={`finding-${f.requirementId}`}
                          as="div"
                        >
                          <p className="stamp-label">Extracted evidence</p>
                          <blockquote className="mt-1 text-sm italic text-ink">
                            “
                            {
                              f.evidence[
                                Math.min(cursor, f.evidence.length - 1)
                              ].quote
                            }
                            ”
                          </blockquote>
                          <p className="mt-1 font-mono text-2xs text-ink-3">
                            page{" "}
                            {
                              f.evidence[
                                Math.min(cursor, f.evidence.length - 1)
                              ].page
                            }{" "}
                            · offset{" "}
                            {
                              f.evidence[
                                Math.min(cursor, f.evidence.length - 1)
                              ].startOffset
                            }
                            –
                            {
                              f.evidence[
                                Math.min(cursor, f.evidence.length - 1)
                              ].endOffset
                            }
                          </p>
                        </ThreadAnchor>
                      </Pullable>

                      {f.evidence.length > 1 ? (
                        <div className="mt-1.5 flex items-center gap-1">
                          <IconButton
                            label="Previous match"
                            icon="chevron-left"
                            disabled={cursor === 0}
                            onClick={() => setCursor((c) => Math.max(0, c - 1))}
                          />
                          <span className="font-mono text-2xs tabular-nums text-ink-3">
                            {Math.min(cursor, f.evidence.length - 1) + 1} of{" "}
                            {f.evidence.length} matches
                          </span>
                          <IconButton
                            label="Next match"
                            icon="chevron-right"
                            disabled={cursor >= f.evidence.length - 1}
                            onClick={() =>
                              setCursor((c) =>
                                Math.min(f.evidence.length - 1, c + 1),
                              )
                            }
                          />
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <p className="mt-2 flex items-start gap-1.5 border-l-2 border-seal pl-3 text-sm text-seal">
                      <Icon
                        name="alert"
                        size={13}
                        className="mt-0.5 shrink-0"
                      />
                      No supporting span was found in the document. This
                      requirement scored zero, and the absence is itself
                      recorded.
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>

          <div className="border-t-2 border-rule-section px-5 py-3">
            <Button
              variant="alarm"
              icon="alert"
              onClick={() => setOverriding(true)}
            >
              Override this assessment
            </Button>
            <p className="mt-2 max-w-[46ch] text-xs text-ink-2">
              Overriding breaks the seal on this entry. It requires a written
              reason and is recorded permanently against your name.
            </p>
          </div>
        </div>

        {/* Document */}
        <div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-8">
            <h2 className="stamp-label">{candidate.resumeId} · page 2 of 4</h2>
            <div className="flex items-center gap-1">
              <IconButton label="Zoom out" icon="zoom-out" />
              <span className="px-1 font-mono text-2xs tabular-nums text-ink-2">
                125%
              </span>
              <IconButton label="Zoom in" icon="zoom-in" />
              <IconButton label="Previous page" icon="chevron-left" />
              <IconButton label="Next page" icon="chevron-right" />
              <IconButton label="Download original document" icon="download" />
            </div>
          </div>

          <div className="bg-recess px-5 py-6 md:px-8">
            <article className="mx-auto max-w-[42rem] border border-rule-entry bg-leaf px-9 py-10">
              <h3 className="text-xl font-semibold track-tight text-ink">
                {candidate.name}
              </h3>
              <p className="mt-0.5 font-mono text-2xs text-ink-3">
                Professional experience · continued
              </p>
              <div className="mt-5 space-y-3.5 text-sm leading-relaxed text-ink-2">
                {RESUME_PAGE_TEXT.map((frag) =>
                  frag.evidenceId ? (
                    <p key={frag.id}>
                      <ThreadAnchor id={`span-${frag.evidenceId}`} as="mark">
                        <span className="bg-stamp-wash box-decoration-clone px-0.5 text-ink shadow-[inset_0_-2px_0_var(--color-stamp)]">
                          {frag.text}
                        </span>
                      </ThreadAnchor>
                    </p>
                  ) : (
                    <p key={frag.id}>{frag.text}</p>
                  ),
                )}
              </div>
              <p className="mt-6 border-t border-rule-hair pt-2 font-mono text-2xs text-ink-3">
                Highlighted spans are the exact character ranges cited by the
                verdicts on the left. Nothing outside a highlight contributed to
                the score.
              </p>
            </article>
          </div>
        </div>
      </div>

      <OverrideDialog
        open={overriding}
        onClose={() => setOverriding(false)}
        candidate={candidate}
      />
    </>
  );
}
