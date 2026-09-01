"use client";

import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { Icon } from "@/components/Icon";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { useGovernanceSummary } from "@/lib/hooks";

export default function GovernancePage() {
  const { data: gov, loading, error } = useGovernanceSummary();

  const auditEntries = gov?.audit_entries ?? [];
  const systemEvents = gov?.system_events ?? [];
  const flagged = auditEntries.find((e) => e.overridden);

  const headHash = gov?.chain_integrity?.head_hash ?? "";
  const verifiedAt = gov?.chain_integrity?.verified_at
    ? new Date(gov.chain_integrity.verified_at).toLocaleTimeString()
    : "—";
  const chainValid = gov?.chain_integrity?.valid ?? false;

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-lg font-medium text-seal">
            Error loading governance data
          </p>
          <p className="text-sm text-ink-3 mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Masthead
        title="Governance &amp; audit"
        meta={
          <>
            <MetaFact label="Register" value="Custody chain" />
            <MetaFact
              label="Head"
              value={`#${gov?.decisions_recorded ?? "—"}`}
              mono
            />
            <MetaFact label="Verified" value={verifiedAt} mono />
          </>
        }
        seal={
          <SealBlock
            tone={chainValid ? "intact" : "broken"}
            label="Chain integrity"
            value={chainValid ? "Valid" : "Tampered"}
            meta={headHash ? `${headHash.slice(0, 14)}…` : "Awaiting verification"}
          />
        }
        actions={
          <Button variant="ruled" icon="download">
            Export audit log
          </Button>
        }
      />


      {/* Integrity facts — a ruled strip of declared figures, not stat cards. */}
      <dl className="grid grid-cols-1 divide-y divide-rule-hair border-b-2 border-rule-section bg-leaf sm:grid-cols-2 sm:divide-x xl:grid-cols-4 xl:divide-y-0">
        <div className="px-5 py-4 md:px-8">
          <dt className="stamp-label">Decisions recorded</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-ink">
            {loading ? "—" : (gov?.decisions_recorded ?? 0).toLocaleString()}
          </dd>
        </div>
        <div className="px-5 py-4 md:px-8 sm:border-t sm:border-rule-hair xl:border-t-0">
          <dt className="stamp-label">Verified events</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-ink">
            {loading ? "—" : (gov?.verified_events ?? 0).toLocaleString()}
          </dd>
          <dd className="font-mono text-2xs text-ink-3">
            last check {verifiedAt}
          </dd>
        </div>
        <div className="px-5 py-4 md:px-8 sm:border-t sm:border-rule-hair xl:border-t-0">
          <dt className="stamp-label">Machine reading</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-ink">
            {loading ? "—" : (gov?.machine_reading_count ?? 0).toLocaleString()}
          </dd>
          <dd className="font-mono text-2xs text-ink-3">
            {gov && gov.verified_events > 0
              ? `${((gov.machine_reading_count / gov.verified_events) * 100).toFixed(1)}% of verified`
              : "—"}
          </dd>
        </div>
        <div className="px-5 py-4 md:px-8 sm:border-t sm:border-rule-hair xl:border-t-0">
          <dt className="stamp-label">Human overrides</dt>
          <dd className="mt-0.5 font-mono text-2xl tabular-nums text-seal">
            {loading ? "—" : (gov?.override_count ?? 0).toLocaleString()}
          </dd>
          <dd className="flex items-center gap-1.5 font-mono text-2xs text-ink-3">
            {gov && gov.verified_events > 0 ? (
              <>
                <span
                  className="inline-flex h-1.5 w-16 border border-seal"
                  aria-hidden="true"
                >
                  <span
                    className="bg-seal"
                    style={{
                      width: `${((gov.override_count / gov.verified_events) * 100).toFixed(1)}%`,
                    }}
                  />
                </span>
                {((gov.override_count / gov.verified_events) * 100).toFixed(1)}%
                agreement gap
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
      </dl>

      <div className="grid grid-cols-1 bg-leaf xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="border-b border-rule-entry xl:border-b-0 xl:border-r">
          <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5 md:px-8">
            <h2 className="stamp-label">Recent entries</h2>
            <Seal tone={chainValid ? "intact" : "broken"}>
              {chainValid ? "Hash chain verified" : "Chain tampered"}
            </Seal>
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
              {loading ? (
                <Tr>
                  <Td colSpan={7} className="text-center py-8">
                    <div className="text-ink-3">Loading audit log...</div>
                  </Td>
                </Tr>
              ) : auditEntries.length === 0 ? (
                <Tr>
                  <Td colSpan={7} className="text-center py-8">
                    <div className="text-ink-3">No audit entries yet</div>
                  </Td>
                </Tr>
              ) : (
                auditEntries.map((e, i) => (
                  <Tr
                    key={e.seq}
                    className={e.overridden ? "bg-seal-wash/40" : ""}
                  >
                    <GutterCell
                      ordinal={e.seq % 100}
                      first={i === 0}
                      last={i === auditEntries.length - 1}
                      broken={e.overridden}
                    />
                    <Td>
                      <div className="font-medium text-ink">
                        {e.candidate_name}
                      </div>
                      <div className="font-mono text-2xs text-ink-3">
                        #{e.seq}
                      </div>
                    </Td>
                    <Td className="font-mono text-2xs text-ink-2">
                      {e.job_id}
                    </Td>
                    <Td className="text-ink-2">{e.ai_verdict}</Td>
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
                          {e.final_decision}
                        </span>
                      </span>
                    </Td>
                    <Td className="text-ink-2">{e.actor}</Td>
                    <Td align="right" className="font-mono text-2xs text-ink-3">
                      {e.hash.slice(0, 16)}…
                    </Td>
                  </Tr>
                ))
              )}
            </tbody>
          </Ledger>
        </div>

        {/* Audit detail + system events */}
        <aside>
          <div className="flex items-center justify-between gap-3 border-b border-rule-entry px-5 py-2.5">
            <h2 className="stamp-label">Audit detail · override</h2>
            {flagged ? (
              <Seal tone="broken">Flagged</Seal>
            ) : (
              <Seal tone="intact">Clean</Seal>
            )}
          </div>

          {flagged ? (
            <div className="border-b-2 border-rule-section px-5 py-4">
              <p className="text-base font-semibold track-tight text-ink">
                {flagged.candidate_name}
              </p>
              <p className="font-mono text-2xs text-ink-3">
                {flagged.candidate_id} · #{flagged.seq}
              </p>

              <dl className="mt-3 divide-y divide-rule-hair border-y border-rule-hair">
                <div className="flex items-baseline justify-between py-2">
                  <dt className="stamp-label">Machine reading</dt>
                  <dd className="font-mono text-sm tabular-nums text-ink">
                    {flagged.ai_verdict}
                  </dd>
                </div>
                <div className="flex items-baseline justify-between py-2">
                  <dt className="stamp-label">Recorded decision</dt>
                  <dd className="font-narrow text-xs font-semibold uppercase track-stamp text-seal">
                    {flagged.final_decision}
                  </dd>
                </div>
                <div className="flex items-baseline justify-between py-2">
                  <dt className="stamp-label">Actor</dt>
                  <dd className="text-sm text-ink">{flagged.actor}</dd>
                </div>
              </dl>

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
            {systemEvents.length === 0 ? (
              <li className="text-sm text-ink-3">No events recorded.</li>
            ) : (
              systemEvents.map((ev, i) => (
                <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
                  {i < systemEvents.length - 1 ? (
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
                        : ev.tone === "success"
                          ? "border-stamp bg-stamp"
                          : "border-rule-entry bg-leaf"
                    }`}
                  />
                  <div className="min-w-0">
                    <p className="text-sm text-ink">{ev.label}</p>
                    <p className="font-mono text-2xs text-ink-3">
                      {new Date(ev.at).toLocaleTimeString()}
                    </p>
                  </div>
                </li>
              ))
            )}
          </ol>
        </aside>
      </div>
    </>
  );
}
