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
import { CANDIDATES } from "@/lib/demo";

export const metadata = { title: "Candidates — TalentLens" };

export default function CandidatesPage() {
  return (
    <>
      <Masthead
        title="Candidates"
        meta={
          <>
            <MetaFact label="Register" value="Assessments" />
            <MetaFact label="Entries" value={CANDIDATES.length} mono />
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
        <SelectField label="Decision" defaultValue="all" className="w-44">
          <option value="all">Any decision</option>
          <option>Advance</option>
          <option>Hold</option>
          <option>Awaiting review</option>
        </SelectField>
        <SelectField label="Custody" defaultValue="all" className="w-44">
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
          {CANDIDATES.map((c, i) => (
            <Tr key={c.id}>
              <GutterCell
                ordinal={i + 1}
                first={i === 0}
                last={i === CANDIDATES.length - 1}
                broken={c.overridden}
              />
              <Td>
                <Link
                  href={`/candidates/${c.id}`}
                  className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                >
                  {c.name}
                </Link>
                <div className="font-mono text-2xs text-ink-3">
                  {c.id} · {c.resumeId}
                </div>
              </Td>
              <Td className="text-ink-2">Senior Frontend Engineer</Td>
              <Td align="right" className="font-mono tabular-nums text-ink">
                {c.score}
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
                  <Seal tone={c.overridden ? "broken" : "intact"}>
                    {c.decision === "advance" ? "Advance" : "Hold"}
                    {c.overridden ? " · overridden" : ""}
                  </Seal>
                )}
              </Td>
              <Td align="right" className="font-mono text-2xs text-ink-3">
                {c.decidedBy ?? "—"}
              </Td>
            </Tr>
          ))}
        </tbody>
      </Ledger>
    </>
  );
}
