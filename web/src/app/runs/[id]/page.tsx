import Link from "next/link";
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
import { CANDIDATES, AUDIT_ENTRIES } from "@/lib/demo";

export const metadata = { title: "Ranked assessment — TalentLens" };

export default async function RankedAssessment({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const overrides = CANDIDATES.filter((c) => c.overridden).length;

  return (
    <ThreadProvider>
      <Masthead
        crumbs={[
          { label: "Screening runs", href: "/runs" },
          { label: "Senior Frontend Engineer", href: "/jobs" },
          { label: id.toUpperCase() },
        ]}
        title="Ranked assessment"
        meta={
          <>
            <MetaFact label="Run" value={id.toUpperCase()} mono />
            <MetaFact label="Rubric" value="v4 sealed" mono />
            <MetaFact label="Closed" value="14:12 · 29 Aug" mono />
          </>
        }
        seal={
          <SealBlock
            tone={overrides ? "pending" : "intact"}
            label="Chain of custody"
            value={overrides ? `${overrides} override` : "Chain intact"}
            meta={`${AUDIT_ENTRIES.length + 37} entries · 0x9f8a…4b2c`}
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
          {CANDIDATES.map((c, i) => (
            <Tr key={c.id}>
              <GutterCell
                ordinal={i + 1}
                first={i === 0}
                last={i === CANDIDATES.length - 1}
                broken={c.overridden}
              />
              <Td>
                <ThreadAnchor id={`cand-${c.id}`} as="div">
                  <Link
                    href={`/candidates/${c.id}`}
                    className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                  >
                    {c.name}
                  </Link>
                  <div className="font-mono text-2xs text-ink-3">
                    {c.id} · {c.resumeId}
                  </div>
                </ThreadAnchor>
              </Td>
              <Td align="right">
                <Pullable
                  chain={[`cand-${c.id}`, `score-${c.id}`]}
                  label={`Pull the provenance thread for ${c.name}'s aggregate score`}
                  className="ml-auto flex w-full items-center justify-end gap-3"
                >
                  <span
                    className="flex h-2.5 w-24 border border-rule-entry"
                    aria-hidden="true"
                  >
                    <span
                      className={c.overridden ? "bg-ochre" : "bg-stamp"}
                      style={{ width: `${c.score}%` }}
                    />
                  </span>
                  <ThreadAnchor id={`score-${c.id}`} as="span">
                    <span className="font-mono text-base tabular-nums text-ink">
                      {c.score}
                    </span>
                    <span className="font-mono text-2xs text-ink-3">/100</span>
                  </ThreadAnchor>
                </Pullable>
              </Td>
              <Td>
                <Seal
                  tone={c.recommendation === "strong" ? "intact" : "neutral"}
                >
                  {c.recommendation === "strong" ? "Strong match" : "Match"}
                </Seal>
              </Td>
              <Td>
                {c.decision === "pending" ? (
                  <Seal tone="pending">Awaiting review</Seal>
                ) : (
                  <>
                    <Seal
                      tone={c.decision === "advance" ? "intact" : "neutral"}
                    >
                      {c.decision === "advance" ? "Advance" : "Hold"}
                    </Seal>
                    <div className="mt-0.5 font-mono text-2xs text-ink-3">
                      {c.decidedBy}
                    </div>
                  </>
                )}
              </Td>
              <Td align="center">
                {c.overridden ? (
                  <span
                    className="inline-flex items-center gap-1 font-narrow text-2xs font-semibold uppercase track-stamp text-seal"
                    title={c.overrideReason ?? undefined}
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
                  href={`/candidates/${c.id}`}
                  className="inline-flex items-center gap-1 font-narrow text-2xs font-semibold uppercase track-stamp text-stamp no-underline hover:underline"
                >
                  Open
                  <Icon name="chevron-right" size={13} />
                </Link>
              </Td>
            </Tr>
          ))}
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
            1–7 of 42
          </span>
          <Button variant="quiet" iconAfter="chevron-right">
            Next
          </Button>
        </div>
      </div>
    </ThreadProvider>
  );
}
