/**
 * SYNTHETIC DEMONSTRATION DATA.
 *
 * Every name, filename, score, hash and timestamp in this file is fabricated
 * for interface demonstration. No real candidate, employer or applicant data
 * appears here, and none of these figures represent measured performance.
 * Surfaces that render this data must carry a visible synthetic-data notice.
 */

export const SYNTHETIC_NOTICE =
  "Synthetic demonstration data — no real candidate records.";

export type RubricStatus = "approved" | "draft";

export type Job = {
  id: string;
  title: string;
  department: string;
  rubric: RubricStatus;
  rubricVersion: string;
  resumes: number;
  latestRun: string | null;
  latestRunAt: string | null;
};

export const JOBS: Job[] = [
  {
    id: "JOB-2291",
    title: "Senior Frontend Engineer",
    department: "Engineering",
    rubric: "approved",
    rubricVersion: "v4",
    resumes: 218,
    latestRun: "SR-294",
    latestRunAt: "2026-08-27 14:02",
  },
  {
    id: "JOB-2288",
    title: "Data Platform Engineer",
    department: "Engineering",
    rubric: "approved",
    rubricVersion: "v2",
    resumes: 143,
    latestRun: "SR-291",
    latestRunAt: "2026-08-26 09:41",
  },
  {
    id: "JOB-2284",
    title: "Compliance Analyst",
    department: "Legal & Risk",
    rubric: "draft",
    rubricVersion: "v1 draft",
    resumes: 64,
    latestRun: null,
    latestRunAt: null,
  },
  {
    id: "JOB-2279",
    title: "Product Designer, Enterprise",
    department: "Design",
    rubric: "approved",
    rubricVersion: "v3",
    resumes: 187,
    latestRun: "SR-288",
    latestRunAt: "2026-08-24 16:18",
  },
  {
    id: "JOB-2271",
    title: "Talent Operations Lead",
    department: "People",
    rubric: "draft",
    rubricVersion: "v2 draft",
    resumes: 39,
    latestRun: null,
    latestRunAt: null,
  },
  {
    id: "JOB-2265",
    title: "Site Reliability Engineer",
    department: "Engineering",
    rubric: "approved",
    rubricVersion: "v5",
    resumes: 256,
    latestRun: "SR-283",
    latestRunAt: "2026-08-21 11:07",
  },
];

export type ParseStatus = "parsed" | "processing" | "failed";

export type ResumeRecord = {
  id: string;
  candidate: string;
  filename: string;
  status: ParseStatus;
  ocr: boolean;
  sanitized: "clean" | "unverified";
  pages: number;
  uploaded: string;
  note?: string;
};

export const RESUMES: ResumeRecord[] = [
  {
    id: "RSM-88213",
    candidate: "Jane Doe",
    filename: "jane-doe-frontend-2026.pdf",
    status: "parsed",
    ocr: false,
    sanitized: "clean",
    pages: 4,
    uploaded: "2026-08-27 13:58",
  },
  {
    id: "RSM-88212",
    candidate: "Rizal Pratama",
    filename: "rizal_pratama_cv.pdf",
    status: "parsed",
    ocr: true,
    sanitized: "clean",
    pages: 2,
    uploaded: "2026-08-27 13:51",
  },
  {
    id: "RSM-88211",
    candidate: "Amara Okonkwo",
    filename: "a-okonkwo-resume.docx",
    status: "processing",
    ocr: false,
    sanitized: "unverified",
    pages: 3,
    uploaded: "2026-08-27 13:47",
  },
  {
    id: "RSM-88210",
    candidate: "Unresolved",
    filename: "scan_20260827_0004.pdf",
    status: "failed",
    ocr: true,
    sanitized: "unverified",
    pages: 6,
    uploaded: "2026-08-27 13:44",
    note: "Text layer absent and OCR confidence below threshold on 5 of 6 pages.",
  },
  {
    id: "RSM-88209",
    candidate: "Sofia Lindqvist",
    filename: "lindqvist-s.pdf",
    status: "parsed",
    ocr: false,
    sanitized: "clean",
    pages: 3,
    uploaded: "2026-08-27 13:39",
  },
  {
    id: "RSM-88208",
    candidate: "Kenji Watanabe",
    filename: "kenji-watanabe-2026.pdf",
    status: "parsed",
    ocr: false,
    sanitized: "clean",
    pages: 5,
    uploaded: "2026-08-27 13:30",
  },
];

export type Requirement = {
  id: string;
  text: string;
  mustHave: boolean;
  weight: number;
  minYears: number | null;
  status: "active" | "draft";
};

export const REQUIREMENTS: Requirement[] = [
  {
    id: "REQ-8992-01",
    text: "Production React experience on an application serving authenticated users at scale.",
    mustHave: true,
    weight: 25,
    minYears: 4,
    status: "active",
  },
  {
    id: "REQ-8992-02",
    text: "TypeScript used as the primary language on a shipped codebase, not incidentally.",
    mustHave: true,
    weight: 20,
    minYears: 3,
    status: "active",
  },
  {
    id: "REQ-8992-03",
    text: "Demonstrated accessibility work: WCAG conformance, assistive-technology testing, or remediation.",
    mustHave: false,
    weight: 15,
    minYears: null,
    status: "active",
  },
  {
    id: "REQ-8992-04",
    text: "Ownership of frontend performance budgets with measured before-and-after results.",
    mustHave: false,
    weight: 15,
    minYears: null,
    status: "active",
  },
  {
    id: "REQ-8992-05",
    text: "Mentorship or technical leadership of at least two engineers.",
    mustHave: false,
    weight: 10,
    minYears: 2,
    status: "active",
  },
  {
    id: "REQ-8992-06",
    text: "Design-system authorship or substantial contribution across multiple product surfaces.",
    mustHave: false,
    weight: 0,
    minYears: null,
    status: "draft",
  },
];

export type Verdict = "met" | "partial" | "missing";

export type EvidenceSpan = {
  id: string;
  requirementId: string;
  quote: string;
  page: number;
  startOffset: number;
  endOffset: number;
};

export type RequirementFinding = {
  requirementId: string;
  label: string;
  verdict: Verdict;
  weight: number;
  contribution: number;
  evidence: EvidenceSpan[];
};

export type ResumeFragment = {
  id: string;
  text: string;
  evidenceId?: string;
};

export type Candidate = {
  rank: number;
  id: string;
  name: string;
  initials: string;
  /** The accessioned document this assessment was computed from. */
  resumeId: string;
  score: number;
  recommendation: "strong" | "match" | "review";
  decision: "advance" | "hold" | "pending";
  /** The named person who recorded the decision. Null while awaiting review. */
  decidedBy?: string;
  overridden: boolean;
  overrideReason?: string;
  findings: RequirementFinding[];
};

export const CANDIDATES: Candidate[] = [
  {
    rank: 1,
    id: "CND-40118",
    name: "Jane Doe",
    initials: "JD",
    resumeId: "RSM-88213",
    score: 92,
    recommendation: "strong",
    decision: "advance",
    decidedBy: "A. Wijaya",
    overridden: false,
    findings: [
      {
        requirementId: "REQ-8992-01",
        label: "Production React at scale",
        verdict: "met",
        weight: 25,
        contribution: 25,
        evidence: [
          {
            id: "EV-1",
            requirementId: "REQ-8992-01",
            quote:
              "Led the rebuild of the authenticated billing console in React, serving roughly 180,000 monthly active accounts.",
            page: 2,
            startOffset: 1184,
            endOffset: 1301,
          },
          {
            id: "EV-1b",
            requirementId: "REQ-8992-01",
            quote:
              "Six years of continuous React delivery across three products.",
            page: 1,
            startOffset: 412,
            endOffset: 473,
          },
        ],
      },
      {
        requirementId: "REQ-8992-02",
        label: "TypeScript as primary language",
        verdict: "met",
        weight: 20,
        contribution: 20,
        evidence: [
          {
            id: "EV-2",
            requirementId: "REQ-8992-02",
            quote:
              "Migrated a 240,000-line JavaScript codebase to strict-mode TypeScript over two quarters.",
            page: 2,
            startOffset: 1466,
            endOffset: 1556,
          },
        ],
      },
      {
        requirementId: "REQ-8992-03",
        label: "Accessibility work",
        verdict: "partial",
        weight: 15,
        contribution: 8,
        evidence: [
          {
            id: "EV-3",
            requirementId: "REQ-8992-03",
            quote:
              "Ran a keyboard-navigation audit across the checkout flow and closed the resulting defects.",
            page: 3,
            startOffset: 208,
            endOffset: 299,
          },
        ],
      },
      {
        requirementId: "REQ-8992-04",
        label: "Performance budgets",
        verdict: "met",
        weight: 15,
        contribution: 15,
        evidence: [
          {
            id: "EV-4",
            requirementId: "REQ-8992-04",
            quote:
              "Reduced largest contentful paint from 4.1s to 1.6s and held the budget in CI for eighteen months.",
            page: 3,
            startOffset: 640,
            endOffset: 741,
          },
        ],
      },
      {
        requirementId: "REQ-8992-05",
        label: "Mentorship",
        verdict: "partial",
        weight: 10,
        contribution: 6,
        evidence: [
          {
            id: "EV-5",
            requirementId: "REQ-8992-05",
            quote:
              "Mentored two junior engineers through their first production releases.",
            page: 3,
            startOffset: 980,
            endOffset: 1050,
          },
        ],
      },
    ],
  },
  {
    rank: 2,
    id: "CND-40092",
    name: "Kenji Watanabe",
    initials: "KW",
    resumeId: "RSM-88208",
    score: 88,
    recommendation: "strong",
    decision: "advance",
    decidedBy: "A. Wijaya",
    overridden: false,
    findings: [],
  },
  {
    rank: 3,
    id: "CND-40147",
    name: "Amara Okonkwo",
    initials: "AO",
    resumeId: "RSM-88211",
    score: 84,
    recommendation: "match",
    decision: "hold",
    decidedBy: "A. Wijaya",
    overridden: true,
    overrideReason:
      "Candidate's platform work is stronger than the rubric captures; the rubric has no requirement covering build tooling, which is central to this role. Raised for panel review rather than held on score.",
    findings: [],
  },
  {
    rank: 4,
    id: "CND-40203",
    name: "Sofia Lindqvist",
    initials: "SL",
    resumeId: "RSM-88209",
    score: 79,
    recommendation: "match",
    decision: "pending",
    overridden: false,
    findings: [],
  },
  {
    rank: 5,
    id: "CND-40155",
    name: "Rizal Pratama",
    initials: "RP",
    resumeId: "RSM-88212",
    score: 76,
    recommendation: "match",
    decision: "pending",
    overridden: false,
    findings: [],
  },
  {
    rank: 6,
    id: "CND-40188",
    name: "Marcus Bell",
    initials: "MB",
    resumeId: "RSM-88207",
    score: 71,
    recommendation: "review",
    decision: "pending",
    overridden: false,
    findings: [],
  },
  {
    rank: 7,
    id: "CND-40174",
    name: "Priya Raman",
    initials: "PR",
    resumeId: "RSM-88206",
    score: 68,
    recommendation: "review",
    decision: "pending",
    overridden: false,
    findings: [],
  },
];

export type AuditEntry = {
  seq: number;
  candidate: string;
  jobId: string;
  aiVerdict: string;
  finalDecision: string;
  actor: string;
  timestamp: string;
  overridden: boolean;
  hash: string;
};

export const AUDIT_ENTRIES: AuditEntry[] = [
  {
    seq: 45210,
    candidate: "Amara Okonkwo",
    jobId: "JOB-2291",
    aiVerdict: "Match · 84",
    finalDecision: "Hold for panel",
    actor: "A. Wijaya",
    timestamp: "2026-08-27 15:12:04",
    overridden: true,
    hash: "0x9f8a41c6b2e04b2c",
  },
  {
    seq: 45209,
    candidate: "Jane Doe",
    jobId: "JOB-2291",
    aiVerdict: "Strong match · 92",
    finalDecision: "Advance",
    actor: "A. Wijaya",
    timestamp: "2026-08-27 15:09:41",
    overridden: false,
    hash: "0x77c3ad10e9f5512b",
  },
  {
    seq: 45208,
    candidate: "Kenji Watanabe",
    jobId: "JOB-2291",
    aiVerdict: "Strong match · 88",
    finalDecision: "Advance",
    actor: "A. Wijaya",
    timestamp: "2026-08-27 15:08:16",
    overridden: false,
    hash: "0x2b6e05df8c14a730",
  },
  {
    seq: 45207,
    candidate: "Marcus Bell",
    jobId: "JOB-2291",
    aiVerdict: "Needs review · 71",
    finalDecision: "Advance",
    actor: "D. Sutanto",
    timestamp: "2026-08-27 14:58:33",
    overridden: true,
    hash: "0x4e19bb72c0a63d81",
  },
  {
    seq: 45206,
    candidate: "Sofia Lindqvist",
    jobId: "JOB-2288",
    aiVerdict: "Match · 79",
    finalDecision: "Pending",
    actor: "system",
    timestamp: "2026-08-27 14:41:02",
    overridden: false,
    hash: "0x8d52f7a3149be6c0",
  },
];

export type SystemEvent = {
  id: string;
  at: string;
  label: string;
  detail: string;
  tone: "neutral" | "alarm" | "seal";
};

export const SYSTEM_EVENTS: SystemEvent[] = [
  {
    id: "SE-9",
    at: "15:12:04",
    label: "Override recorded",
    detail: "CND-40147 · reason captured · chain link 45210",
    tone: "alarm",
  },
  {
    id: "SE-8",
    at: "15:04:55",
    label: "Chain verified",
    detail: "12,450 events replayed, 0 divergences",
    tone: "seal",
  },
  {
    id: "SE-7",
    at: "14:02:11",
    label: "Run completed",
    detail: "SR-294 · 218 candidates · rubric v4",
    tone: "neutral",
  },
  {
    id: "SE-6",
    at: "13:58:40",
    label: "Rubric frozen",
    detail: "REQ-8992 v4 approved by A. Wijaya",
    tone: "seal",
  },
  {
    id: "SE-5",
    at: "13:44:09",
    label: "Parse failure",
    detail: "RSM-88210 · OCR confidence below threshold",
    tone: "alarm",
  },
];

export const RESUME_PAGE_TEXT: ResumeFragment[] = [
  {
    id: "p2-1",
    text: "Senior Frontend Engineer, Northwind Systems — 2021 to present. ",
  },
  {
    id: "p2-2",
    text: "Led the rebuild of the authenticated billing console in React, serving roughly 180,000 monthly active accounts.",
    evidenceId: "EV-1",
  },
  {
    id: "p2-3",
    text: " Partnered with the payments team on a phased cutover with no customer-facing downtime. ",
  },
  {
    id: "p2-4",
    text: "Migrated a 240,000-line JavaScript codebase to strict-mode TypeScript over two quarters.",
    evidenceId: "EV-2",
  },
  {
    id: "p2-5",
    text: " Introduced contract tests between the console and three internal services, cutting integration regressions substantially over the following year. Ran the frontend guild and set the review standards the team still uses.",
  },
];

export const RUN = {
  id: "SR-90210",
  jobTitle: "Senior Frontend Engineer",
  jobId: "JOB-2291",
  rubricVersion: "v4",
  processed: 142,
  total: 218,
  percent: 65,
  etaMinutes: 4,
  startedAt: "2026-08-27 13:46",
  stages: [
    {
      n: 1,
      label: "Resume processing",
      state: "done" as const,
      detail: "218 of 218 parsed",
    },
    {
      n: 2,
      label: "Requirement evaluation",
      state: "done" as const,
      detail: "1,308 verdicts recorded",
    },
    {
      n: 3,
      label: "Evidence extraction",
      state: "active" as const,
      detail: "142 of 218 candidates cited",
    },
    {
      n: 4,
      label: "Score calculation",
      state: "queued" as const,
      detail: "Deterministic aggregation",
    },
    {
      n: 5,
      label: "Ranking",
      state: "queued" as const,
      detail: "Awaiting complete scores",
    },
  ],
};
