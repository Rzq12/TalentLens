import { Masthead, MetaFact } from "@/components/shell/Masthead";
import { Button } from "@/components/ui/Button";
import { SealBlock } from "@/components/ui/Seal";
import { ThreadProvider } from "@/components/thread/ThreadProvider";
import { CandidateEvidenceClient } from "./CandidateEvidenceClient";

// Server component — fetch candidate data on the server side
async function fetchCandidate(id: string) {
  try {
    const apiBase =
      process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
    const res = await fetch(`${apiBase}/candidates/${id}`, {
      next: { revalidate: 30 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function CandidateEvidence({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const candidate = await fetchCandidate(id);

  if (!candidate) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-lg font-medium text-seal">Candidate not found</p>
          <p className="text-sm text-ink-3 mt-2">ID: {id}</p>
        </div>
      </div>
    );
  }

  return (
    <ThreadProvider>
      <Masthead
        crumbs={[
          { label: "Screening runs", href: "/runs" },
          { label: candidate.run_id, href: `/runs/${candidate.run_id}` },
          { label: candidate.candidate_id },
        ]}
        title={`Evidence · ${candidate.candidate_id}`}
        meta={
          <>
            <MetaFact label="Assessment" value={candidate.candidate_id} mono />
            <MetaFact label="Document" value={candidate.document_id} mono />
            <MetaFact label="Run" value={candidate.run_id} mono />
          </>
        }
        seal={
          <SealBlock
            tone={candidate.overridden ? "broken" : "intact"}
            label="Custody"
            value={candidate.overridden ? "Seal broken" : "Unbroken"}
            meta={candidate.decided_by ?? "awaiting review"}
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
      <CandidateEvidenceClient candidate={candidate} />
    </ThreadProvider>
  );
}
