"use client";

import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { SealBlock } from "@/components/ui/Seal";
import { SyntheticNotice } from "@/components/ui/Section";
import { RubricEditorAPI } from "@/components/rubric/RubricEditorAPI";
import { useRubrics } from "@/lib/hooks";
import { useSearchParams } from "next/navigation";

export default function RubricsPage() {
  const searchParams = useSearchParams();
  const rubricId = searchParams.get("rubricId") ?? undefined;
  const jobId = searchParams.get("jobId") ?? undefined;

  // Load rubrics filtered by job if jobId is specified, else all recent
  const { data: rubricsData, loading } = useRubrics(jobId, 10);
  const rubrics = rubricsData ?? [];
  const rubric = rubricId
    ? rubrics.find((r) => r.rubric_id === rubricId)
    : rubrics[0];

  const isDraft = rubric?.status === "draft" || !rubric;

  return (
    <>
      <Masthead
        crumbs={[
          { label: "Jobs", href: "/jobs" },
          rubric
            ? {
                label: rubric.job_id,
                href: `/jobs`,
              }
            : { label: "Select job", href: "/jobs" },
          { label: rubric ? `Rubric ${rubric.rubric_id}` : "New rubric" },
        ]}
        title="Screening rubric"
        meta={
          <>
            <MetaFact label="Rubric" value={rubric?.rubric_id ?? "—"} mono />
            <MetaFact
              label="Version"
              value={
                rubric
                  ? `${rubric.version} ${isDraft ? "draft" : "sealed"}`
                  : "—"
              }
              mono
            />
            <MetaFact
              label="Status"
              value={loading ? "Loading…" : (rubric?.status ?? "—")}
              mono
            />
          </>
        }
        seal={
          <SealBlock
            tone={isDraft ? "draft" : "intact"}
            label="Seal"
            value={isDraft ? "Unsealed draft" : "Sealed"}
            meta={isDraft ? "editable" : "frozen"}
          />
        }
      />
      <SyntheticNotice />
      <RubricEditorAPI
        rubric={rubric ?? null}
        loading={loading}
        jobId={jobId}
      />
    </>
  );
}
