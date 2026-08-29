import { notFound } from "next/navigation";
import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { SealBlock } from "@/components/ui/Seal";
import { SyntheticNotice } from "@/components/ui/Section";
import { ThreadProvider } from "@/components/thread/ThreadProvider";
import { EvidencePane } from "@/components/evidence/EvidencePane";
import { CANDIDATES } from "@/lib/demo";

export function generateStaticParams() {
  return CANDIDATES.map((c) => ({ id: c.id }));
}

export default async function CandidateEvidence({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const candidate = CANDIDATES.find((c) => c.id === id);
  if (!candidate) notFound();

  return (
    <ThreadProvider>
      <Masthead
        crumbs={[
          { label: "Screening runs", href: "/runs" },
          { label: "SR-294", href: "/runs/SR-294" },
          { label: candidate.name },
        ]}
        title={`Evidence · ${candidate.name}`}
        meta={
          <>
            <MetaFact label="Assessment" value={candidate.id} mono />
            <MetaFact label="Document" value={candidate.resumeId} mono />
            <MetaFact label="Rubric" value="v4 sealed" mono />
          </>
        }
        seal={
          <SealBlock
            tone={candidate.overridden ? "broken" : "intact"}
            label="Custody"
            value={candidate.overridden ? "Seal broken" : "Unbroken"}
            meta={candidate.decidedBy ?? "awaiting review"}
          />
        }
        actions={
          <>
            <Button variant="ruled" icon="flag">
              Flag for review
            </Button>
            <Button variant="stamp" icon="check">
              Confirm evidence
            </Button>
          </>
        }
      />
      <SyntheticNotice />
      <EvidencePane candidate={candidate} />
    </ThreadProvider>
  );
}
