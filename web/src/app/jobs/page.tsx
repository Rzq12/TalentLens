import Link from "next/link";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { TextField, SelectField } from "@/components/ui/Field";
import {
  Toolbar,
  SyntheticNotice,
  NeverRejectsNote,
} from "@/components/ui/Section";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import { JOBS } from "@/lib/demo";

export const metadata = { title: "Jobs — TalentLens" };

export default function JobsPage() {
  return (
    <>
      <Masthead
        title="Open positions"
        meta={
          <>
            <MetaFact label="Register" value="Positions" />
            <MetaFact label="Entries" value={JOBS.length} mono />
            <MetaFact label="Tenant" value="demo" mono />
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
        actions={
          <Button variant="stamp" icon="plus">
            Open a position
          </Button>
        }
      />

      <SyntheticNotice />

      <Toolbar>
        <TextField
          label="Find a position"
          placeholder="Title, identifier or department"
          icon="search"
          className="min-w-[16rem] flex-1"
        />
        <SelectField label="Department" defaultValue="all" className="w-44">
          <option value="all">All departments</option>
          <option>Engineering</option>
          <option>Design</option>
          <option>Legal &amp; Risk</option>
          <option>People</option>
        </SelectField>
        <SelectField label="Rubric" defaultValue="all" className="w-40">
          <option value="all">Any state</option>
          <option>Approved</option>
          <option>Draft</option>
        </SelectField>
      </Toolbar>

      <div className="bg-leaf px-5 py-2.5 md:px-8">
        <NeverRejectsNote />
      </div>

      <Ledger className="border-t-2 border-rule-section bg-leaf">
        <LedgerHead>
          <Th width="4rem" align="center">
            Seq
          </Th>
          <Th>Position</Th>
          <Th width="11rem">Department</Th>
          <Th width="11rem">Rubric</Th>
          <Th width="7rem" align="right">
            Resumes
          </Th>
          <Th width="13rem">Latest run</Th>
          <Th width="12rem" align="right">
            Action
          </Th>
        </LedgerHead>
        <tbody>
          {JOBS.map((job, i) => {
            const draft = job.rubric === "draft";
            return (
              <Tr key={job.id}>
                <GutterCell
                  ordinal={i + 1}
                  first={i === 0}
                  last={i === JOBS.length - 1}
                  broken={draft}
                />
                <Td>
                  <Link
                    href={`/runs/${job.latestRun ?? "SR-294"}`}
                    className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                  >
                    {job.title}
                  </Link>
                  <div className="font-mono text-2xs text-ink-3">{job.id}</div>
                </Td>
                <Td className="text-ink-2">{job.department}</Td>
                <Td>
                  <Seal tone={draft ? "draft" : "intact"}>
                    {draft ? "Draft" : "Approved"}
                  </Seal>
                  <span className="ml-2 font-mono text-2xs text-ink-3">
                    {job.rubricVersion}
                  </span>
                </Td>
                <Td align="right" className="font-mono tabular-nums text-ink">
                  {job.resumes}
                </Td>
                <Td>
                  {job.latestRun ? (
                    <>
                      <Link
                        href={`/runs/${job.latestRun}`}
                        className="font-mono text-xs text-ink no-underline hover:text-stamp hover:underline"
                      >
                        {job.latestRun}
                      </Link>
                      <div className="font-mono text-2xs text-ink-3">
                        {job.latestRunAt}
                      </div>
                    </>
                  ) : (
                    <span className="text-xs text-ink-3">No run recorded</span>
                  )}
                </Td>
                <Td align="right">
                  <Button
                    variant={draft ? "ruled" : "stamp"}
                    disabled={draft}
                    icon="run"
                    title={
                      draft
                        ? "The rubric must be approved and frozen before a run can start"
                        : undefined
                    }
                  >
                    Start screening
                  </Button>
                </Td>
              </Tr>
            );
          })}
        </tbody>
      </Ledger>

      <div className="flex items-center justify-between border-t border-rule-entry bg-leaf px-5 py-2.5 md:px-8">
        <p className="text-xs text-ink-3">
          A position with a draft rubric cannot be screened. Approving a rubric
          freezes it and stamps a version onto every score it produces.
        </p>
        <span className="stamp-label shrink-0">
          {JOBS.length} of {JOBS.length}
        </span>
      </div>
    </>
  );
}
