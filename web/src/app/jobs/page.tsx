"use client";

import { useState } from "react";
import Link from "next/link";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { TextField, SelectField } from "@/components/ui/Field";
import {
  Toolbar,
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
import { useJobs } from "@/lib/hooks";

export default function JobsPage() {
  const { data: jobsData, loading, error } = useJobs(50);
  const jobs = jobsData ?? [];
  const [filter, setFilter] = useState({ department: "all", rubric: "all" });

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-lg font-medium text-seal">Error loading jobs</p>
          <p className="text-sm text-ink-3 mt-2">{error.message}</p>
        </div>
      </div>
    );
  }

  const filteredJobs = jobs.filter((job) => {
    if (filter.department !== "all" && job.department !== filter.department) {
      return false;
    }
    if (filter.rubric !== "all" && job.status !== filter.rubric.toLowerCase()) {
      return false;
    }
    return true;
  });

  return (
    <>
      <Masthead
        title="Open positions"
        meta={
          <>
            <MetaFact label="Register" value="Positions" />
            <MetaFact label="Entries" value={filteredJobs.length} mono />
          </>
        }
        seal={
          <SealBlock
            tone="intact"
            label="Register state"
            value="Chain intact"
            meta="Verified by backend"
          />
        }
        actions={
          <Button variant="stamp" icon="plus">
            Open a position
          </Button>
        }
      />


      <Toolbar>
        <TextField
          label="Find a position"
          placeholder="Title, identifier or department"
          icon="search"
          className="min-w-[16rem] flex-1"
        />
        <SelectField
          label="Department"
          defaultValue="all"
          className="w-44"
          onChange={(e) =>
            setFilter({ ...filter, department: e.currentTarget.value })
          }
        >
          <option value="all">All departments</option>
          <option>Engineering</option>
          <option>Design</option>
          <option>Legal &amp; Risk</option>
          <option>People</option>
        </SelectField>
        <SelectField
          label="Rubric"
          defaultValue="all"
          className="w-40"
          onChange={(e) =>
            setFilter({ ...filter, rubric: e.currentTarget.value })
          }
        >
          <option value="all">Any state</option>
          <option value="approved">Approved</option>
          <option value="draft">Draft</option>
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
          {loading ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">Loading jobs...</div>
              </Td>
            </Tr>
          ) : filteredJobs.length === 0 ? (
            <Tr>
              <Td colSpan={7} className="text-center py-8">
                <div className="text-ink-3">No jobs found</div>
              </Td>
            </Tr>
          ) : (
            filteredJobs.map((job, i) => {
              const draft = job.status === "draft";
              return (
                <Tr key={job.job_id}>
                  <GutterCell
                    ordinal={i + 1}
                    first={i === 0}
                    last={i === filteredJobs.length - 1}
                    broken={draft}
                  />
                  <Td>
                    <Link
                      href={`/runs/${job.latest_screening_run_id ?? "SR-294"}`}
                      className="font-medium text-ink no-underline hover:text-stamp hover:underline"
                    >
                      {job.title}
                    </Link>
                    <div className="font-mono text-2xs text-ink-3">
                      {job.job_id}
                    </div>
                  </Td>
                  <Td className="text-ink-2">{job.department || "—"}</Td>
                  <Td>
                    <Seal tone={draft ? "draft" : "intact"}>
                      {draft ? "Draft" : "Approved"}
                    </Seal>
                  </Td>
                  <Td align="right" className="font-mono tabular-nums text-ink">
                    {job.resume_count || 0}
                  </Td>
                  <Td>
                    {job.latest_screening_run_id ? (
                      <>
                        <Link
                          href={`/runs/${job.latest_screening_run_id}`}
                          className="font-mono text-xs text-ink no-underline hover:text-stamp hover:underline"
                        >
                          {job.latest_screening_run_id}
                        </Link>
                        <div className="font-mono text-2xs text-ink-3">
                          {job.created_at}
                        </div>
                      </>
                    ) : (
                      <span className="text-xs text-ink-3">
                        No run recorded
                      </span>
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
            })
          )}
        </tbody>
      </Ledger>

      <div className="flex items-center justify-between border-t border-rule-entry bg-leaf px-5 py-2.5 md:px-8">
        <p className="text-xs text-ink-3">
          A position with a draft rubric cannot be screened. Approving a rubric
          freezes it and stamps a version onto every score it produces.
        </p>
        <span className="stamp-label shrink-0">
          {filteredJobs.length} of {jobs.length}
        </span>
      </div>
    </>
  );
}
