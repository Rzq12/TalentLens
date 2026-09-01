"use client";

import { useState } from "react";
import Link from "next/link";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { TextField, SelectField } from "@/components/ui/Field";
import { Toolbar, SyntheticNotice } from "@/components/ui/Section";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { useCandidates } from "@/lib/hooks";
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

export default function CandidatesPage() {
  const { data: candidates = [], loading, error } = useCandidates(undefined, 50);
  const [decisionFilter, setDecisionFilter] = useState("all");
  const [custodyFilter, setCustodyFilter] = useState("all");

  const filtered = candidates.filter((c) => {
    if (decisionFilter !== "all" && c.decision !== decisionFilter) return false;
    if (custodyFilter === "Unbroken" && c.overridden) return false;
    if (custodyFilter === "Seal broken" && !c.overridden) return false;
    return true;
  });

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-lg font-medium text-seal">
            Error loading candidates
          </p>
          <p className="text-sm text-ink-3 mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Masthead
        title="Candidates"
        meta={
          <>
            <MetaFact label="Register" value="Assessments" />
            <MetaFact label="Entries" value={candidates.length} mono />
          </>
        }
        seal={
          <SealBlock
            tone="intact"
            label="Register state"
            value="Chain intact"
            meta="0x9f8a…4b2c"
          />
        }
      />

      <SyntheticNotice />

      <Toolbar>
        <TextField
          label="Search assessments"
          placeholder="Name, identifier or evidence text"
          icon="search"
          className="min-w-[16rem] flex-1"
        />
        <SelectField
          label="Decision"
          defaultValue="all"
          className="w-44"
          onChange={(e) => setDecisionFilter(e.currentTarget.value)}
        >
          <option value="all">Any decision</option>
          <option value="advance">Advance</option>
          <option value="hold">Hold</option>
          <option value="reject">Reject</option>
        </SelectField>
        <SelectField
          label="Custody"
          defaultValue="all"
          className="w-44"
          onChange={(e) => setCustodyFilter(e.currentTarget.value)}
        >
          <option value="all">Any state</option>
          <option>Unbroken</option>
          <option>Seal broken</option>
        </SelectField>
      </Toolbar>

      <Ledger className="border-t-2 border-rule-section bg-leaf">
        <LedgerHead>
          <Th width="4rem" align="center">
            Seq
          </Th>
          <Th>Candidate</Th>
          <Th width="10rem">Position</Th>
          <Th width="8rem" align="right">
            Aggregate
          </Th>
          <Th width="11rem">Model reading</Th>
          <Th width="12rem">Human decision</Th>
          <Th width="9rem" align="right">
            Recorded
          </Th>
        </LedgerHead>
        <tbody>
          {loading ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">Loading candidates...</div>
              </Td>
            </Tr>
          ) : filtered.length === 0 ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">No candidates found</div>
              </Td>
            </Tr>
          ) : (
            filtered.map((c, i) => (
              <Tr key={c.candidate_id}>
                <GutterCell
                  ordinal={i + 1}
                  first={i === 0}
                  last={i === filtered.length - 1}
                  broken={c.overridden}
                />
                <Td>
                  <Link
                    href={`/candidates/${c.candidate_id}`}
                    className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                  >
                    {c.candidate_id}
                  </Link>
                  <div className="font-mono text-2xs text-ink-3">
                    {c.candidate_id} · {c.document_id}
                  </div>
                </Td>
                <Td className="text-ink-2">{c.run_id}</Td>
                <Td align="right" className="font-mono tabular-nums text-ink">
                  {Math.round(c.score * 100)}
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
                    <Seal tone={c.overridden ? "broken" : "intact"}>
                      {c.decision.charAt(0).toUpperCase() + c.decision.slice(1)}
                      {c.overridden ? " · overridden" : ""}
                    </Seal>
                  )}
                </Td>
                <Td align="right" className="font-mono text-2xs text-ink-3">
                  {c.decided_by ?? "—"}
                </Td>
              </Tr>
            ))
          )}
        </tbody>
      </Ledger>
    </>
  );
}
