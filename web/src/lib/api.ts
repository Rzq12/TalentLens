/**
 * TalentLens API Client
 *
 * Consumes the FastAPI backend at `/api/v1/`.
 * All responses are strongly typed from the backend schemas.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

type RequestMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface FetchOptions {
  method?: RequestMethod;
  headers?: Record<string, string>;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined>;
}

/**
 * Internal fetch wrapper with JSON serialization and error handling.
 */
async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const { method = "GET", headers = {}, body, query } = options;

  // Build query string
  let url = `${API_BASE}${path}`;
  if (query) {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        params.append(key, String(value));
      }
    });
    if (params.toString()) {
      url += `?${params.toString()}`;
    }
  }

  const requestHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...headers,
  };

  // Add auth token if available
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("auth_token");
    if (token) {
      requestHeaders.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(url, {
    method,
    headers: requestHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      `API error ${response.status}: ${error.detail || "Unknown error"}`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ============================================================================
// Jobs API
// ============================================================================

export interface JobSummary {
  job_id: string;
  title: string;
  department?: string;
  location?: string;
  employment_type?: string;
  seniority?: string;
  status: "draft" | "approved";
  created_at: string;
  requirement_count?: number;
  latest_screening_run_id?: string;
  resume_count?: number;
}

export interface JobListResponse {
  items: JobSummary[];
  count: number;
  next_cursor?: string | null;
}

export interface JobResponse extends JobSummary {
  description_raw: string;
  rubric_version?: string;
}

export const jobsAPI = {
  list: async (limit = 50, before?: string): Promise<JobListResponse> => {
    const response = await apiFetch<{
      items: Array<Omit<JobSummary, "job_id"> & { id: string }>;
      count: number;
      next_cursor?: string | null;
    }>("/jobs", { query: { limit, before } });
    return {
      ...response,
      items: response.items.map(({ id, ...job }) => ({ ...job, job_id: id })),
    };
  },

  get: async (jobId: string): Promise<JobResponse> => {
    const job = await apiFetch<{
      id: string;
      title: string;
      description_raw: string;
      department?: string;
      location?: string;
      employment_type?: string;
      seniority?: string;
      status: JobResponse["status"];
      created_at: string;
    }>(`/jobs/${jobId}`);
    return { ...job, job_id: job.id };
  },

  create: async (data: {
    title: string;
    description_raw: string;
    department?: string;
    location?: string;
    employment_type?: string;
    seniority?: string;
  }): Promise<JobResponse> => {
    const job = await apiFetch<{
      id: string;
      title: string;
      description_raw: string;
      department?: string;
      location?: string;
      employment_type?: string;
      seniority?: string;
      status: JobResponse["status"];
      created_at: string;
    }>("/jobs", { method: "POST", body: data });
    return { ...job, job_id: job.id };
  },

  uploadDocument: async (file: File, title: string) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title);

    const token =
      typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
    const headers: Record<string, string> = {};
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}/jobs/upload`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    const job = (await response.json()) as {
      id: string;
      title: string;
      description_raw: string;
      department?: string;
      location?: string;
      employment_type?: string;
      seniority?: string;
      status: JobResponse["status"];
      created_at: string;
    };
    return { ...job, job_id: job.id };
  },
};

// ============================================================================
// Resumes API
// ============================================================================

export interface ResumeSummary {
  document_id: string;
  filename: string;
  media_type: string;
  page_count: number;
  parse_status: "ok" | "low_yield" | "failed";
  created_at: string;
  needs_ocr?: boolean;
  injection_risk_score?: number;
}

export interface ResumeListResponse {
  items: ResumeSummary[];
  count: number;
  next_cursor?: string | null;
}

export interface ResumeUploadResponse extends ResumeSummary {
  candidate_id: string;
  profile_id: string;
  size_bytes: number;
  sha256: string;
  deduplicated: boolean;
  quarantined: boolean;
}

export interface ResumeDetailResponse extends ResumeSummary {
  size_bytes: number;
  sha256: string;
  needs_ocr: boolean;
  parser_version: string;
  text: string;
  injection_risk_score: number;
  quarantined: boolean;
  sanitization_report: Record<string, unknown>;
}

export const resumesAPI = {
  list: (limit = 50, before?: string) =>
    apiFetch<ResumeListResponse>("/resumes", { query: { limit, before } }),

  get: (documentId: string) =>
    apiFetch<ResumeDetailResponse>(`/resumes/${documentId}`),

  upload: async (
    file: File,
    candidateName: string,
    candidateEmail?: string,
    consentGranted = false,
  ): Promise<ResumeUploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("candidate_name", candidateName);
    if (candidateEmail) formData.append("candidate_email", candidateEmail);
    formData.append("consent_granted", String(consentGranted));

    const token =
      typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
    const headers: Record<string, string> = {};
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}/resumes`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    return response.json() as Promise<ResumeUploadResponse>;
  },
};

// ============================================================================
// Rubrics API
// ============================================================================

export interface RequirementRow {
  requirement_id: string;
  label: string;
  description?: string;
  must_have: boolean;
  weight: number;
  min_years?: number;
  verdict?: "met" | "partial" | "missing";
  contribution?: number;
}

export interface RubricResponse {
  rubric_id: string;
  job_id: string;
  version: string;
  status: "draft" | "approved" | "superseded";
  requirements: RequirementRow[];
  created_at: string;
}

export interface RubricListResponse {
  items: RubricResponse[];
  count: number;
  next_cursor?: string | null;
}

interface BackendRubricResponse {
  rubric_version_id: string;
  job_id: string;
  version: number;
  status: RubricResponse["status"] | "superseded";
  requirements: Array<{
    id: string;
    text: string;
    is_must_have: boolean;
    weight: number;
    min_years?: number | null;
  }>;
}

const mapRubric = (rubric: BackendRubricResponse): RubricResponse => ({
  rubric_id: rubric.rubric_version_id,
  job_id: rubric.job_id,
  version: String(rubric.version),
  status: rubric.status,
  requirements: rubric.requirements.map((requirement) => ({
    requirement_id: requirement.id,
    label: requirement.text,
    must_have: requirement.is_must_have,
    weight: Number(requirement.weight) * 100,
    min_years: requirement.min_years ?? undefined,
  })),
  created_at: new Date().toISOString(),
});

export const rubricsAPI = {
  list: async (jobId?: string, limit = 50, before?: string) => {
    const response = await apiFetch<{
      items: BackendRubricResponse[];
      count: number;
      next_cursor?: string | null;
    }>("/rubrics", { query: { job_id: jobId, limit, before } });
    return { ...response, items: response.items.map(mapRubric) };
  },

  get: async (rubricId: string) =>
    mapRubric(await apiFetch<BackendRubricResponse>(`/rubrics/${rubricId}`)),

  create: async (data: {
    job_id: string;
    requirements: Omit<RequirementRow, "requirement_id">[];
  }): Promise<RubricResponse> => {
    const response = await apiFetch<BackendRubricResponse>("/rubrics", {
      method: "POST",
      body: {
        job_id: data.job_id,
        requirements: data.requirements.map((requirement) => ({
          text: requirement.label,
          category: "skill",
          is_must_have: requirement.must_have,
          weight: requirement.weight / 100,
          min_years: requirement.min_years,
        })),
      },
    });
    return mapRubric(response);
  },

  update: async (rubricId: string, data: Partial<RubricResponse>) => {
    const response = await apiFetch<BackendRubricResponse>(
      `/rubrics/${rubricId}/requirements`,
      {
        method: "POST",
        body: {
          requirements: (data.requirements ?? []).map((requirement) => ({
            text: requirement.label,
            category: "skill",
            is_must_have: requirement.must_have,
            weight: requirement.weight / 100,
            min_years: requirement.min_years,
          })),
        },
      },
    );
    return mapRubric(response);
  },

  approve: async (rubricId: string) =>
    mapRubric(
      await apiFetch<BackendRubricResponse>(`/rubrics/${rubricId}/approve`, {
        method: "POST",
      }),
    ),
};

// ============================================================================
// Screening Runs API
// ============================================================================

export interface ScreeningRunStage {
  n: number;
  label: string;
  state: "pending" | "in_progress" | "done" | "failed";
  detail?: string;
  progress?: number;
}

export interface ScreeningRunResponse {
  run_id: string;
  job_id: string;
  rubric_version: string;
  status: "queued" | "running" | "completed" | "paused" | "failed";
  total_resumes: number;
  processed: number;
  etaMinutes?: number;
  stages: ScreeningRunStage[];
  started_at?: string;
  completed_at?: string;
  created_at: string;
}

export interface ScreeningRunListResponse {
  items: ScreeningRunResponse[];
  count: number;
  next_cursor?: string | null;
}

interface BackendScreeningRun {
  run_id: string;
  job_id: string;
  status: ScreeningRunResponse["status"];
  candidate_count: number;
  started_at?: string | null;
  completed_at?: string | null;
}

const mapScreeningRun = (run: BackendScreeningRun): ScreeningRunResponse => ({
  run_id: run.run_id,
  job_id: run.job_id,
  rubric_version: "",
  status: run.status,
  total_resumes: run.candidate_count,
  processed: run.candidate_count,
  stages: [],
  started_at: run.started_at ?? undefined,
  completed_at: run.completed_at ?? undefined,
  created_at: run.started_at ?? new Date().toISOString(),
});

export interface RunResult {
  score_id: string;
  rank: number;
  candidate_id: string;
  overall_score: number;
  recommendation: "strong_advance" | "advance" | "hold" | "not_a_fit";
  recommendation_confidence?: number;
  summary?: string;
  skill_gaps?: unknown[];
  interview_questions?: unknown[];
  verdicts?: unknown[];
}

export interface RunResultsResponse {
  run_id: string;
  status: string;
  count: number;
  results: RunResult[];
}

export const screeningAPI = {
  list: async (jobId?: string, limit = 50, before?: string) => {
    const response = await apiFetch<{
      items: BackendScreeningRun[];
      count: number;
      next_cursor?: string | null;
    }>("/screening/runs", { query: { job_id: jobId, limit, before } });
    return { ...response, items: response.items.map(mapScreeningRun) };
  },

  get: async (runId: string) =>
    mapScreeningRun(
      await apiFetch<BackendScreeningRun>(`/screening/runs/${runId}`),
    ),

  events: (runId: string) => `${API_BASE}/screening/runs/${runId}/events`,

  /** Start a run — posted to /jobs/{jobId}/runs (screening router handles it) */
  start: (jobId: string) =>
    apiFetch<{ run_id: string; status: string; events_url: string }>(
      `/screening/jobs/${jobId}/runs`,
      { method: "POST" },
    ),

  /** Get ranked results for a run (populated once status=completed|running) */
  results: (runId: string) =>
    apiFetch<RunResultsResponse>(`/screening/runs/${runId}/results`),
};

// ============================================================================
// Assessment & Candidates API
// ============================================================================

export interface EvidenceSpan {
  id: string;
  requirement_id: string;
  quote: string;
  page: number;
  start_offset: number;
  end_offset: number;
}

export interface RequirementFinding {
  requirement_id: string;
  label: string;
  verdict: "met" | "partial" | "missing";
  weight: number;
  contribution: number;
  evidence: EvidenceSpan[];
}

export interface CandidateAssessment {
  score_id: string;
  candidate_id: string;
  run_id: string;
  rank: number;
  score: number;
  recommendation: "strong_advance" | "advance" | "hold" | "not_a_fit";
  decision?: "advance" | "hold" | "reject" | null;
  decided_by?: string;
  decided_at?: string;
  overridden: boolean;
  override_reason?: string;
  findings: RequirementFinding[];
  resume_id: string;
  document_id: string;
}

export interface CandidateListResponse {
  items: CandidateAssessment[];
  count: number;
  next_cursor?: string | null;
}

export const candidatesAPI = {
  /**
   * List candidates for a run via the screening results endpoint.
   * Falls back to an empty list if no runId provided.
   */
  list: async (runId?: string, _limit = 50) => {
    if (!runId) {
      return apiFetch<CandidateListResponse>("/candidates", {
        query: { limit: _limit },
      });
    }
    const res = await apiFetch<RunResultsResponse>(
      `/screening/runs/${runId}/results`,
    );
    // Map RunResult → CandidateAssessment shape
    const items: CandidateAssessment[] = (res.results ?? []).map((r) => ({
      score_id: r.score_id,
      candidate_id: r.candidate_id,
      run_id: runId,
      rank: r.rank,
      score: r.overall_score,
      recommendation: r.recommendation,
      decision: null,
      decided_by: undefined,
      decided_at: undefined,
      overridden: false,
      override_reason: undefined,
      findings: [],
      resume_id: r.candidate_id,
      document_id: r.candidate_id,
    }));
    return {
      items,
      count: items.length,
      next_cursor: null,
    } as CandidateListResponse;
  },

  get: (candidateId: string) =>
    apiFetch<CandidateAssessment>(`/candidates/${candidateId}`),

  /**
   * Record a decision via the governance endpoint.
   * The score_id in this context is the candidateId (candidate_score.id).
   */
  recordDecision: (
    scoreId: string,
    data: { decision: "advance" | "hold" | "reject"; reason?: string },
  ) =>
    apiFetch<{ decision_id: string; score_id: string; decision: string }>(
      `/governance/scores/${scoreId}/decisions`,
      { method: "POST", body: data },
    ),

  override: (
    verdictId: string,
    data: { verdict: "met" | "partial" | "missing"; reason: string },
  ) =>
    apiFetch<void>(`/governance/verdicts/${verdictId}/override`, {
      method: "POST",
      body: data,
    }),
};

// ============================================================================
// Governance & Audit API
// ============================================================================

export interface AuditEntry {
  seq: number;
  candidate_id: string;
  candidate_name: string;
  job_id: string;
  ai_verdict: string;
  final_decision: string;
  actor: string;
  hash: string;
  overridden: boolean;
  created_at: string;
}

export interface SystemEvent {
  label: string;
  tone: "info" | "success" | "warning" | "alarm";
  at: string;
}

export interface GovernanceResponse {
  decisions_recorded: number;
  verified_events: number;
  machine_reading_count: number;
  override_count: number;
  audit_entries: AuditEntry[];
  system_events: SystemEvent[];
  chain_integrity: {
    valid: boolean;
    head_hash: string;
    verified_at: string;
  };
}

export const governanceAPI = {
  /**
   * Verify the audit chain for the current tenant.
   * Returns validity + count of checked events.
   */
  verifyChain: () =>
    apiFetch<{
      valid: boolean;
      checked_events: number;
      first_invalid_event_id: string | null;
    }>("/governance/audit/verify"),

  recordDecision: (
    scoreId: string,
    data: { decision: string; reason?: string },
  ) =>
    apiFetch<{ decision_id: string; score_id: string; decision: string }>(
      `/governance/scores/${scoreId}/decisions`,
      { method: "POST", body: data },
    ),
};

// ============================================================================
// Search API
// ============================================================================

export interface SearchResult {
  document_id: string;
  score: number;
  spans: Array<{
    chunk_id: string;
    content: string;
    section: string;
    page_from: number;
    page_to: number;
    start_char: number;
    end_char: number;
    score: number;
  }>;
}

export interface SearchResponse {
  items: SearchResult[];
  count: number;
  query: string;
  mode: string;
}

export const searchAPI = {
  semantic: (query: string, limit = 20) =>
    apiFetch<SearchResponse>("/search/candidates", {
      method: "POST",
      body: { query, top_k: limit, mode: "semantic" },
    }),

  lexical: (query: string, limit = 20) =>
    apiFetch<SearchResponse>("/search/candidates", {
      method: "POST",
      body: { query, top_k: limit, mode: "lexical" },
    }),

  similar: (documentId: string, limit = 20) =>
    apiFetch<SearchResponse>("/search/similar", {
      method: "POST",
      body: { document_id: documentId, top_k: limit },
    }),
};

// ============================================================================
// Auth API (if needed)
// ============================================================================

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  tenant_id: string;
  role: string;
}

export const authAPI = {
  me: () =>
    apiFetch<{ user_id: string; tenant_id: string; roles: string[] }>(
      "/auth/me",
    ),

  logout: () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("auth_token");
    }
  },
};

export default {
  jobs: jobsAPI,
  resumes: resumesAPI,
  rubrics: rubricsAPI,
  screening: screeningAPI,
  candidates: candidatesAPI,
  governance: governanceAPI,
  search: searchAPI,
  auth: authAPI,
};
