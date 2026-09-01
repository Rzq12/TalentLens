/**
 * React hooks for TalentLens API
 *
 * Use in client components to fetch data from the backend.
 */

"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import API, {
  JobSummary,
  JobListResponse,
  JobResponse,
  ResumeSummary,
  ResumeListResponse,
  ResumeDetailResponse,
  RubricListResponse,
  RubricResponse,
  ScreeningRunListResponse,
  ScreeningRunResponse,
  CandidateListResponse,
  CandidateAssessment,
  AuditEntry,
  SystemEvent,
  SearchResponse,
} from "./api";

interface UseQueryState<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
}

interface UseInfiniteState<TItem> {
  data: TItem[] | null;
  loading: boolean;
  error: Error | null;
  hasMore: boolean;
  nextCursor?: string;
  loadMore: () => void;
  isLoadingMore: boolean;
}

/**
 * Generic hook for fetching data with loading and error states.
 */
function useQuery<T>(
  fetchFn: () => Promise<T>,
  deps: React.DependencyList = [],
): UseQueryState<T> {
  const [state, setState] = useState<UseQueryState<T>>({
    data: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let mounted = true;

    (async () => {
      try {
        setState((prev) => ({ ...prev, loading: true }));
        const result = await fetchFn();
        if (mounted) {
          setState({ data: result, loading: false, error: null });
        }
      } catch (err) {
        if (mounted) {
          setState({
            data: null,
            loading: false,
            error: err instanceof Error ? err : new Error(String(err)),
          });
        }
      }
    })();

    return () => {
      mounted = false;
    };
  }, deps);

  return state;
}

/**
 * Hook for infinite/pagination queries.
 * TItem is the type of each individual item in the list.
 */
function useInfiniteQuery<TItem>(
  fetchFn: (
    cursor?: string,
  ) => Promise<{ items: TItem[]; next_cursor?: string | null }>,
  deps: React.DependencyList = [],
): UseInfiniteState<TItem> {
  const [data, setData] = useState<TItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [nextCursor, setNextCursor] = useState<string>();
  const [hasMore, setHasMore] = useState(true);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    setData([]);
    setLoading(true);
    setError(null);
    setNextCursor(undefined);
    setHasMore(true);

    (async () => {
      try {
        const result = await fetchFn();
        if (mounted.current) {
          setData(result.items);
          setNextCursor(result.next_cursor ?? undefined);
          setHasMore(!!result.next_cursor);
          setError(null);
        }
      } catch (err) {
        if (mounted.current) {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      } finally {
        if (mounted.current) {
          setLoading(false);
        }
      }
    })();

    return () => {
      mounted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const loadMore = useCallback(async () => {
    if (!nextCursor || isLoadingMore) return;

    try {
      setIsLoadingMore(true);
      const result = await fetchFn(nextCursor);
      if (mounted.current) {
        setData((prev) => [...prev, ...result.items]);
        setNextCursor(result.next_cursor ?? undefined);
        setHasMore(!!result.next_cursor);
      }
    } catch (err) {
      if (mounted.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (mounted.current) {
        setIsLoadingMore(false);
      }
    }
  }, [nextCursor, isLoadingMore]);

  return {
    data,
    loading,
    error,
    hasMore,
    nextCursor,
    loadMore,
    isLoadingMore,
  };
}

// ============================================================================
// Jobs Hooks
// ============================================================================

export function useJobs(limit = 50) {
  return useInfiniteQuery<JobSummary>(
    (cursor) => API.jobs.list(limit, cursor),
    [limit],
  );
}

export function useJob(jobId: string) {
  return useQuery(() => API.jobs.get(jobId), [jobId]);
}

export function useCreateJob() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const create = useCallback(
    async (data: Parameters<typeof API.jobs.create>[0]) => {
      try {
        setLoading(true);
        setError(null);
        const result = await API.jobs.create(data);
        return result;
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return { create, loading, error };
}

// ============================================================================
// Resumes Hooks
// ============================================================================

export function useResumes(limit = 50) {
  return useInfiniteQuery<ResumeSummary>(
    (cursor) => API.resumes.list(limit, cursor),
    [limit],
  );
}

export function useResumeDetail(documentId: string) {
  return useQuery(() => API.resumes.get(documentId), [documentId]);
}

export function useUploadResume() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [progress, setProgress] = useState(0);

  const upload = useCallback(
    async (
      file: File,
      candidateName: string,
      candidateEmail?: string,
      consentGranted = false,
    ) => {
    try {
      setLoading(true);
      setError(null);
      setProgress(0);

      // Simulate progress
      const progressInterval = setInterval(() => {
        setProgress((p) => Math.min(p + 10, 90));
      }, 100);

      const result = await API.resumes.upload(
        file,
        candidateName,
        candidateEmail,
        consentGranted,
      );
      clearInterval(progressInterval);
      setProgress(100);
      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
    }, [],
  );

  return { upload, loading, error, progress };
}

// ============================================================================
// Rubrics Hooks
// ============================================================================

export function useRubrics(jobId?: string, limit = 50) {
  return useInfiniteQuery<RubricResponse>(
    (cursor) => API.rubrics.list(jobId, limit, cursor),
    [jobId, limit],
  );
}

export function useRubric(rubricId: string) {
  return useQuery(() => API.rubrics.get(rubricId), [rubricId]);
}

export function useCreateRubric() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const create = useCallback(
    async (data: Parameters<typeof API.rubrics.create>[0]) => {
      try {
        setLoading(true);
        setError(null);
        return await API.rubrics.create(data);
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return { create, loading, error };
}

export function useApproveRubric() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const approve = useCallback(async (rubricId: string) => {
    try {
      setLoading(true);
      setError(null);
      return await API.rubrics.approve(rubricId);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  return { approve, loading, error };
}

// ============================================================================
// Screening Runs Hooks
// ============================================================================

export function useScreeningRuns(jobId?: string, limit = 50) {
  return useInfiniteQuery<ScreeningRunResponse>(
    (cursor) => API.screening.list(jobId, limit, cursor),
    [jobId, limit],
  );
}

export function useScreeningRun(runId: string) {
  return useQuery(() => API.screening.get(runId), [runId]);
}

export function useStartScreening() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const start = useCallback(async (jobId: string) => {
    try {
      setLoading(true);
      setError(null);
      return await API.screening.start(jobId);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setError(error);
      throw error;
    } finally {
      setLoading(false);
    }
  }, []);

  return { start, loading, error };
}

/** Pause is not yet implemented in the backend. This hook is a stub. */
export function usePauseScreening() {
  const pause = useCallback(async (_runId: string) => {
    throw new Error("Pause is not yet supported by the backend.");
  }, []);
  return { pause, loading: false, error: null };
}

// ============================================================================
// Candidates Hooks
// ============================================================================

export function useCandidates(runId?: string, limit = 50) {
  // candidatesAPI.list does not paginate — returns all results from the run
  const { data, loading, error } = useQuery(
    () => API.candidates.list(runId, limit),
    [runId, limit],
  );
  return {
    data: data?.items ?? [],
    loading,
    error,
    hasMore: false,
    loadMore: () => {},
    isLoadingMore: false,
  };
}

export function useCandidate(candidateId: string) {
  return useQuery(() => API.candidates.get(candidateId), [candidateId]);
}

export function useRecordDecision() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const record = useCallback(
    async (
      candidateId: string,
      decision: "advance" | "hold" | "reject",
      reason?: string,
    ) => {
      try {
        setLoading(true);
        setError(null);
        return await API.candidates.recordDecision(candidateId, {
          decision,
          reason,
        });
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return { record, loading, error };
}

export function useOverrideDecision() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const override = useCallback(
    async (candidateId: string, _decision: string, reason: string) => {
      // The backend override endpoint is per-verdict, not per-candidate.
      // For now we record a governance decision against the score_id.
      try {
        setLoading(true);
        setError(null);
        return await API.governance.recordDecision(candidateId, {
          decision: _decision,
          reason,
        });
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  return { override, loading, error };
}

// ============================================================================
// Governance Hooks
// ============================================================================

/**
 * Verify the audit chain for the current tenant.
 * Returns { valid, checked_events, first_invalid_event_id }.
 */
export function useGovernanceVerify() {
  return useQuery(() => API.governance.verifyChain(), []);
}

/**
 * Kept for backward-compat — maps governance verify result into a
 * summary-shaped object so existing page code keeps working.
 */
export function useGovernanceSummary() {
  const result = useGovernanceVerify();
  return {
    ...result,
    data: result.data
      ? {
          decisions_recorded: result.data.checked_events,
          verified_events: result.data.checked_events,
          machine_reading_count: 0,
          override_count: 0,
          audit_entries: [] as AuditEntry[],
          system_events: [] as SystemEvent[],
          chain_integrity: {
            valid: result.data.valid,
            head_hash: result.data.first_invalid_event_id ?? "0x000…",
            verified_at: new Date().toISOString(),
          },
        }
      : null,
  };
}

// ============================================================================
// Search Hooks
// ============================================================================

export function useSemanticSearch(query: string, limit = 20) {
  return useQuery(
    () =>
      query
        ? API.search.semantic(query, limit)
        : Promise.resolve({ items: [], count: 0, query, mode: "semantic" }),
    [query, limit],
  );
}

export function useLexicalSearch(query: string, limit = 20) {
  return useQuery(
    () =>
      query
        ? API.search.lexical(query, limit)
        : Promise.resolve({ items: [], count: 0, query, mode: "lexical" }),
    [query, limit],
  );
}
