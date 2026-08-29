import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { Icon } from "@/components/Icon";
import { SyntheticNotice } from "@/components/ui/Section";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { AUDIT_ENTRIES, SYSTEM_EVENTS, CANDIDATES } from "@/lib/demo";

export const metadata = { title: "Governance & audit — TalentLens" };

const flagged = CANDIDATES.find((c) => c.overridden);

export default function GovernancePage() {
  return (
    <>
      <Masthead
        title="Governance &amp; audit"
        meta={
          <>
            <MetaFact label="Register" value="Custody chain" />
            <MetaFact label="Head" value="#45210" mono />
            <MetaFact label="Verified" value="15:04 · 29 Aug" mono />
          </>
        }
        seal={
          <SealBlock
            tone="intact"
            label="Chain integrity"
            value="Valid"
            meta="0x9f8a…4b2c"
          />
        }
        actions={
          <Button variant="ruled" icon="download">
            Export audit log
          </Button>
        }
      />

      <SyntheticNotice />

      {/* Integrity facts — a ruled strip of declared figures, not stat cards. */}
      <dl className="grid grid-cols-1 divide-y divide-rule-hair border-b-2 border-rule-section bg-leaf sm:grid-cols-2 sm:divide-x xl:grid-cols-4 xl:divide-y-0">
        <div className="px-5 py-4 md:px-8">
          <dt className="stamp-label">Decisions recorded</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-ink">
            45,210
          </dd>
        </div>
        <div className="px-5 py-4 md:px-8 sm:border-t sm:border-rule-hair xl:border-t-0">
          <dt className="stamp-label">Verified events</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-ink">
            12,450
          </dd>
          <dd className="font-mono text-2xs text-ink-3">last check 15:04</dd>
        </div>
        <div className="px-5 py-4 md:px-8 sm:border-t sm:border-rule-hair xl:border-t-0">
          <dt className="stamp-label">Machine reading</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-ink">
            11,920
          </dd>
          <dd className="font-mono text-2xs text-ink-3">95.8% of verified</dd>
        </div>
        <div className="px-5 py-4 md:px-8 sm:border-t sm:border-rule-hair xl:border-t-0">
          <dt className="stamp-label">Human overrides</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-seal">
            530
          </dd>
          <dd className="flex items-center gap-1.5 font-mono text-2xs text-ink-3">
            <span
              className="inline-flex h-1.5 w-16 border border-seal"
              aria-hidden="true"
            >
              <span className="bg-seal" style={{ width: "42%" }} />
            </span>
            4.2% agreement gap
          </dd>
        </div>
      </dl>

      <div className="grid grid-cols-1 bg-leaf xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="border-b border-rule-entry xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-8">
            <h2 className="stamp-label">Recent entries</h2>
            <Seal tone="intact">Hash chain verified</Seal>
          </div>
          <Ledger>
            <LedgerHead>
              <Th width="4rem" align="center">
                Seq
              </Th>
              <Th>Candidate</Th>
              <Th width="7rem">Position</Th>
              <Th width="9rem">Machine</Th>
              <Th width="10rem">Recorded decision</Th>
              <Th width="9rem">Actor</Th>
              <Th width="9rem" align="right">
                Hash
              </Th>
            </LedgerHead>
            <tbody>
              {AUDIT_ENTRIES.map((e, i) => (
                <Tr
                  key={e.seq}
                  className={e.overridden ? "bg-seal-wash/40" : ""}
                >
                  <GutterCell
                    ordinal={e.seq % 100}
                    first={i === 0}
                    last={i === AUDIT_ENTRIES.length - 1}
                    broken={e.overridden}
                  />
                  <Td>
                    <div className="font-medium text-ink">{e.candidate}</div>
                    <div className="font-mono text-2xs text-ink-3">
                      #{e.seq}
                    </div>
                  </Td>
                  <Td className="font-mono text-2xs text-ink-2">{e.jobId}</Td>
                  <Td className="text-ink-2">{e.aiVerdict}</Td>
                  <Td>
                    <span className="flex items-center gap-1.5">
                      {e.overridden ? (
                        <Icon
                          name="alert"
                          size={13}
                          className="shrink-0 text-seal"
                        />
                      ) : null}
                      <span className={e.overridden ? "text-seal" : "text-ink"}>
                        {e.finalDecision}
                      </span>
                    </span>
                  </Td>
                  <Td className="text-ink-2">{e.actor}</Td>
                  <Td align="right" className="font-mono text-2xs text-ink-3">
                    {e.hash}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Ledger>
        </div>

        {/* Audit detail + system events */}
        <aside>
          <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5">
            <h2 className="stamp-label">Audit detail · override</h2>
            <Seal tone="broken">Flagged</Seal>
          </div>

          {flagged ? (
            <div className="border-b-2 border-rule-section px-5 py-4">
              <p className="text-base font-semibold track-tight text-ink">
                {flagged.name}
              </p>
              <p className="font-mono text-2xs text-ink-3">
                {flagged.id} · {flagged.resumeId}
              </p>

              <dl className="mt-3 divide-y divide-rule-hair border-y border-rule-hair">
                <div className="flex items-baseline justify-between py-2">
                  <dt className="stamp-label">Machine reading</dt>
                  <dd className="font-mono text-sm tabular-nums text-ink">
                    {flagged.score} · strong match
                  </dd>
                </div>
                <div className="flex items-baseline justify-between py-2">
                  <dt className="stamp-label">Recorded decision</dt>
                  <dd className="font-narrow text-xs font-semibold uppercase track-stamp text-seal">
                    Hold
                  </dd>
                </div>
                <div className="flex items-baseline justify-between py-2">
                  <dt className="stamp-label">Actor</dt>
                  <dd className="text-sm text-ink">{flagged.decidedBy}</dd>
                </div>
              </dl>

              <div className="mt-3">
                <p className="stamp-label">Written reason</p>
                <blockquote className="mt-1 border-l-2 border-seal pl-3 text-sm italic text-ink">
                  “{flagged.overrideReason}”
                </blockquote>
              </div>

              <p className="mt-3 flex items-start gap-1.5 text-xs text-ink-2">
                <Icon
                  name="thread"
                  size={13}
                  className="mt-0.5 shrink-0 text-ink-3"
                />
                This entry can be replayed byte-for-byte: resume, rubric,
                prompt, model and embedding versions are all stamped onto it.
              </p>
            </div>
          ) : null}

          <div className="border-b border-rule-entry px-5 py-2.5">
            <h2 className="stamp-label">System event log</h2>
          </div>
          <ol className="px-5 py-3">
            {SYSTEM_EVENTS.map((ev, i) => (
              <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
                {i < SYSTEM_EVENTS.length - 1 ? (
                  <span
                    aria-hidden="true"
                    className="absolute left-[5px] top-4 bottom-0 w-[1px] bg-rule-hair"
                  />
                ) : null}
                <span
                  aria-hidden="true"
                  className={`relative z-[1] mt-1.5 h-2.5 w-2.5 shrink-0 border ${
                    ev.tone === "alarm"
                      ? "border-seal bg-seal"
                      : ev.tone === "seal"
                        ? "border-stamp bg-stamp"
                        : "border-rule-entry bg-leaf"
                  }`}
                />
                <div className="min-w-0">
                  <p className="text-sm text-ink">{ev.label}</p>
                  <p className="font-mono text-2xs text-ink-3">{ev.at}</p>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </>
  );
}
