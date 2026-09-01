"use client";

import { useState } from "react";
import Link from "next/link";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { Seal, SealBlock } from "@/components/ui/Seal";
import { TextField, SelectField } from "@/components/ui/Field";
import { Toolbar, NeverRejectsNote } from "@/components/ui/Section";
import {
  Ledger,
  LedgerHead,
  Th,
  Td,
  Tr,
  GutterCell,
} from "@/components/ledger/Ledger";
import {
  useCreateJob,
  useJobs,
  useRubrics,
  useStartScreening,
} from "@/lib/hooks";

export default function JobsPage() {
  const { data: jobsData, loading, error } = useJobs(50);
  const jobs = jobsData ?? [];
  const { data: rubricsData } = useRubrics(undefined, 200);
  const rubrics = rubricsData ?? [];
  const { start, loading: starting } = useStartScreening();
  const [filter, setFilter] = useState({ department: "all", rubric: "all" });
  const [openForm, setOpenForm] = useState(false);
  const [form, setForm] = useState({
    title: "",
    description_raw: "",
    department: "",
    location: "",
    employment_type: "",
    seniority: "",
  });
  const { create, loading: creating, error: createError } = useCreateJob();

  const submitJob = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await create({
      ...form,
      department: form.department || undefined,
      location: form.location || undefined,
      employment_type: form.employment_type || undefined,
      seniority: form.seniority || undefined,
    });
    setOpenForm(false);
    window.location.reload();
  };

  const startRun = async (jobId: string) => {
    const result = await start(jobId);
    window.location.href = `/runs/${result.run_id}`;
  };

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
          <Button variant="stamp" icon="plus" onClick={() => setOpenForm(true)}>
            Open a position
          </Button>
        }
      />
      {openForm ? (
        <div className="fixed inset-0 z-40 flex items-start justify-center bg-ink/40 px-4 py-8">
          <form
            onSubmit={submitJob}
            className="w-full max-w-2xl border-2 border-rule-section bg-leaf p-5 shadow-lg md:p-8"
          >
            <div className="flex items-start justify-between gap-4 border-b border-rule-entry pb-4">
              <div>
                <p className="stamp-label">New position</p>
                <h2 className="mt-1 text-2xl font-semibold track-tight text-ink">
                  Open a position
                </h2>
              </div>
              <Button
                variant="quiet"
                icon="cross"
                aria-label="Close position form"
                type="button"
                onClick={() => setOpenForm(false)}
              />
            </div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <TextField
                label="Title"
                required
                value={form.title}
                onChange={(event) =>
                  setForm({ ...form, title: event.target.value })
                }
              />
              <TextField
                label="Department"
                value={form.department}
                onChange={(event) =>
                  setForm({ ...form, department: event.target.value })
                }
              />
              <TextField
                label="Location"
                value={form.location}
                onChange={(event) =>
                  setForm({ ...form, location: event.target.value })
                }
              />
              <TextField
                label="Employment type"
                value={form.employment_type}
                onChange={(event) =>
                  setForm({ ...form, employment_type: event.target.value })
                }
              />
              <TextField
                label="Seniority"
                value={form.seniority}
                onChange={(event) =>
                  setForm({ ...form, seniority: event.target.value })
                }
              />
              <label className="sm:col-span-2">
                <span className="stamp-label">Job description</span>
                <textarea
                  required
                  value={form.description_raw}
                  onChange={(event) =>
                    setForm({ ...form, description_raw: event.target.value })
                  }
                  className="mt-1 min-h-40 w-full border border-rule-entry bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-stamp"
                />
              </label>
            </div>
            {createError ? (
              <p className="mt-4 text-sm text-seal">{createError.message}</p>
            ) : null}
            <div className="mt-6 flex justify-end gap-2 border-t border-rule-entry pt-4">
              <Button
                variant="quiet"
                type="button"
                onClick={() => setOpenForm(false)}
              >
                Cancel
              </Button>
              <Button variant="stamp" type="submit" loading={creating}>
                Create position
              </Button>
            </div>
          </form>
        </div>
      ) : null}

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
              const rubric = rubrics.find((item) => item.job_id === job.job_id);
              const draft = rubric?.status !== "approved";
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
                      href={
                        job.latest_screening_run_id
                          ? `/runs/${job.latest_screening_run_id}`
                          : `/rubrics?jobId=${job.job_id}`
                      }
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
                      disabled={starting}
                      icon={draft ? "sheet" : "run"}
                      onClick={() =>
                        draft
                          ? (window.location.href = `/rubrics?jobId=${job.job_id}`)
                          : startRun(job.job_id)
                      }
                      title={
                        draft
                          ? "Create and approve a rubric before starting a run"
                          : undefined
                      }
                    >
                      {draft ? "Create rubric" : "Start screening"}
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
