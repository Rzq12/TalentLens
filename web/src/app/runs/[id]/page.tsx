"use client";

import Link from "next/link";
import { use } from "react";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { Icon } from "@/components/Icon";
import { SyntheticNotice, NeverRejectsNote } from "@/components/ui/Section";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import {
  ThreadProvider,
  Pullable,
  ThreadAnchor,
} from "@/components/thread/ThreadProvider";
import { useScreeningRun, useCandidates } from "@/lib/hooks";
import type { CandidateAssessment } from "@/lib/api";

function recommendationLabel(rec: CandidateAssessment["recommendation"]) {
  switch (rec) {
    case "strong_advance":
      return "Strong match";
    case "advance":
      return "Match";
    case "hold":
      return "Needs review";
    default:
      return "Not a fit";
  }
}

function recommendationTone(
  rec: CandidateAssessment["recommendation"],
): "intact" | "neutral" | "broken" {
  switch (rec) {
    case "strong_advance":
      return "intact";
    case "advance":
      return "neutral";
    default:
      return "broken";
  }
}

export default function RankedAssessment({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const { data: run, loading: runLoading } = useScreeningRun(id);
  const { data: candidates = [], loading: candidatesLoading } = useCandidates(
    id,
    100,
  );

  const overrides = candidates.filter((c) => c.overridden).length;
  const loading = runLoading || candidatesLoading;

  return (
    <ThreadProvider>
      <Masthead
        crumbs={[
          { label: "Screening runs", href: "/runs" },
          { label: run?.job_id ?? "…", href: "/jobs" },
          { label: id.toUpperCase() },
        ]}
        title="Ranked assessment"
        meta={
          <>
            <MetaFact label="Run" value={id.toUpperCase()} mono />
            <MetaFact
              label="Rubric"
              value={run?.rubric_version ?? "—"}
              mono
            />
            <MetaFact
              label="Closed"
              value={
                run?.completed_at
                  ? new Date(run.completed_at).toLocaleString()
                  : "—"
              }
              mono
            />
          </>
        }
        seal={
          <SealBlock
            tone={overrides ? "pending" : "intact"}
            label="Chain of custody"
            value={overrides ? `${overrides} override` : "Chain intact"}
            meta={`${candidates.length} entries · 0x9f8a…4b2c`}
          />
        }
        actions={
          <>
            <Button variant="ruled" icon="download">
              Export CSV
            </Button>
            <Button variant="stamp" icon="seal">
              Close run
            </Button>
          </>
        }
      />

      <SyntheticNotice />

      <div className="flex flex-wrap items-center justify-between gap-3 bg-leaf px-5 py-2.5 md:px-8">
        <NeverRejectsNote className="max-w-[76ch]" />
        <p className="flex shrink-0 items-center gap-1.5 stamp-label">
          <Icon name="thread" size={13} className="text-stamp" />
          Hover a score to pull its thread
        </p>
      </div>

      <Ledger className="border-t-2 border-rule-section bg-leaf">
        <LedgerHead>
          <Th width="4rem" align="center">
            Rank
          </Th>
          <Th>Candidate</Th>
          <Th width="15rem" align="right">
            Aggregate
          </Th>
          <Th width="12rem">Model reading</Th>
          <Th width="12rem">Human decision</Th>
          <Th width="9rem" align="center">
            Custody
          </Th>
          <Th width="8rem" align="right">
            Evidence
          </Th>
        </LedgerHead>
        <tbody>
          {loading ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">Loading candidates...</div>
              </Td>
            </Tr>
          ) : candidates.length === 0 ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">No candidates for this run</div>
              </Td>
            </Tr>
          ) : (
            candidates.map((c, i) => (
              <Tr key={c.candidate_id}>
                <GutterCell
                  ordinal={c.rank ?? i + 1}
                  first={i === 0}
                  last={i === candidates.length - 1}
                  broken={c.overridden}
                />
                <Td>
                  <ThreadAnchor id={`cand-${c.candidate_id}`} as="div">
                    <Link
                      href={`/candidates/${c.candidate_id}`}
                      className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                    >
                      {c.candidate_id}
                    </Link>
                    <div className="font-mono text-2xs text-ink-3">
                      {c.candidate_id} · {c.document_id}
                    </div>
                  </ThreadAnchor>
                </Td>
                <Td align="right">
                  <Pullable
                    chain={[
                      `cand-${c.candidate_id}`,
                      `score-${c.candidate_id}`,
                    ]}
                    label={`Pull the provenance thread for ${c.candidate_id}'s aggregate score`}
                    className="ml-auto flex w-full items-center justify-end gap-3"
                  >
                    <span
                      className="flex h-2.5 w-24 border border-rule-entry"
                      aria-hidden="true"
                    >
                      <span
                        className={c.overridden ? "bg-ochre" : "bg-stamp"}
                        style={{
                          width: `${Math.round(c.score * 100)}%`,
                        }}
                      />
                    </span>
                    <ThreadAnchor id={`score-${c.candidate_id}`} as="span">
                      <span className="font-mono text-base tabular-nums text-ink">
                        {Math.round(c.score * 100)}
                      </span>
                      <span className="font-mono text-2xs text-ink-3">/100</span>
                    </ThreadAnchor>
                  </Pullable>
                </Td>
                <Td>
                  <Seal tone={recommendationTone(c.recommendation)}>
                    {recommendationLabel(c.recommendation)}
                  </Seal>
                </Td>
                <Td>
                  {!c.decision ? (
                    <Seal tone="pending">Awaiting review</Seal>
                  ) : (
                    <>
                      <Seal
                        tone={c.decision === "advance" ? "intact" : "neutral"}
                      >
                        {c.decision.charAt(0).toUpperCase() +
                          c.decision.slice(1)}
                      </Seal>
                      <div className="mt-0.5 font-mono text-2xs text-ink-3">
                        {c.decided_by}
                      </div>
                    </>
                  )}
                </Td>
                <Td align="center">
                  {c.overridden ? (
                    <span
                      className="inline-flex items-center gap-1 font-narrow text-2xs font-semibold uppercase track-stamp text-seal"
                      title={c.override_reason ?? undefined}
                    >
                      <Icon name="alert" size={13} />
                      Seal broken
                    </span>
                  ) : (
                    <span className="font-mono text-2xs text-ink-3">
                      Unbroken
                    </span>
                  )}
                </Td>
                <Td align="right">
                  <Link
                    href={`/candidates/${c.candidate_id}`}
                    className="inline-flex items-center gap-1 font-narrow text-2xs font-semibold uppercase track-stamp text-stamp no-underline hover:underline"
                  >
                    Open
                    <Icon name="chevron-right" size={13} />
                  </Link>
                </Td>
              </Tr>
            ))
          )}
        </tbody>
      </Ledger>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule-entry bg-leaf px-5 py-2.5 md:px-8">
        <p className="max-w-[70ch] text-xs text-ink-2">
          The continuity tick in the left margin runs unbroken while the ranking
          is the machine&apos;s own arithmetic, and breaks at every entry a
          person changed by hand.
        </p>
        <div className="flex items-center gap-2">
          <Button variant="quiet" icon="chevron-left" disabled>
            Previous
          </Button>
          <span className="font-mono text-2xs tabular-nums text-ink-3">
            1–{candidates.length} of {candidates.length}
          </span>
          <Button variant="quiet" iconAfter="chevron-right" disabled>
            Next
          </Button>
        </div>
      </div>
    </ThreadProvider>
  );
}
