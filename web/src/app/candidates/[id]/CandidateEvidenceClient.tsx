"use client";

import { EvidencePaneAPI } from "@/components/evidence/EvidencePaneAPI";
import type { CandidateAssessment } from "@/lib/api";

interface Props {
  candidate: CandidateAssessment;
}

export function CandidateEvidenceClient({ candidate }: Props) {
  return <EvidencePaneAPI candidate={candidate} />;
}
