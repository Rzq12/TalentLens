"use client";

import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { SealBlock } from "@/components/ui/Seal";
import { RunMonitorAPI } from "@/components/run/RunMonitorAPI";
import { Button } from "@/components/ui/Button";
import { useScreeningRuns } from "@/lib/hooks";
import Link from "next/link";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { Seal } from "@/components/ui/Seal";

export default function RunsPage() {
  const { data: runsData, loading, error } = useScreeningRuns(undefined, 20);
  const runs = runsData ?? [];

  const activeRun = runs.find(
    (r) => r.status === "running" || r.status === "queued",
  );

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-lg font-medium text-seal">
            Error loading screening runs
          </p>
          <p className="text-sm text-ink-3 mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Masthead
        title="Screening runs"
        meta={
          <>
            <MetaFact label="Register" value="Runs" />
            <MetaFact label="Total" value={runs.length} mono />
          </>
        }
        seal={
          <SealBlock
            tone={activeRun ? "pending" : "intact"}
            label="Run state"
            value={activeRun ? "Running" : "Idle"}
            meta={activeRun ? "live" : "no active run"}
          />
        }
        actions={
          activeRun ? (
            <>
              <Button variant="ruled" icon="pause">
                Pause
              </Button>
              <Button variant="alarm" icon="stop">
                Abort
              </Button>
            </>
          ) : undefined
        }
      />

      {activeRun ? <RunMonitorAPI runId={activeRun.run_id} /> : null}

      <Ledger className="border-t-2 border-rule-section bg-leaf">
        <LedgerHead>
          <Th width="4rem" align="center">
            Seq
          </Th>
          <Th>Run</Th>
          <Th width="11rem">Job</Th>
          <Th width="9rem">Status</Th>
          <Th width="8rem" align="right">
            Processed
          </Th>
          <Th width="11rem">Started</Th>
        </LedgerHead>
        <tbody>
          {loading ? (
            <Tr>
              <Td colSpan={6} className="text-center py-8">
                <div className="text-ink-3">Loading runs...</div>
              </Td>
            </Tr>
          ) : runs.length === 0 ? (
            <Tr>
              <Td colSpan={6} className="text-center py-8">
                <div className="text-ink-3">No screening runs yet</div>
              </Td>
            </Tr>
          ) : (
            runs.map((r, i) => (
              <Tr key={r.run_id}>
                <GutterCell
                  ordinal={i + 1}
                  first={i === 0}
                  last={i === runs.length - 1}
                  broken={r.status === "failed"}
                  live={r.status === "running"}
                />
                <Td>
                  <Link
                    href={`/runs/${r.run_id}`}
                    className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                  >
                    {r.run_id}
                  </Link>
                  <div className="font-mono text-2xs text-ink-3">
                    Rubric {r.rubric_version}
                  </div>
                </Td>
                <Td className="font-mono text-2xs text-ink-2">{r.job_id}</Td>
                <Td>
                  <Seal
                    tone={
                      r.status === "completed"
                        ? "intact"
                        : r.status === "running"
                          ? "pending"
                          : r.status === "failed"
                            ? "broken"
                            : "neutral"
                    }
                  >
                    {r.status.charAt(0).toUpperCase() + r.status.slice(1)}
                  </Seal>
                </Td>
                <Td align="right" className="font-mono tabular-nums text-ink-2">
                  {r.processed} / {r.total_resumes}
                </Td>
                <Td className="font-mono text-2xs text-ink-3">
                  {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                </Td>
              </Tr>
            ))
          )}
        </tbody>
      </Ledger>
    </>
  );
}
