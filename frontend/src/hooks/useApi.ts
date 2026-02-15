import { useState, useEffect, useCallback, useRef } from 'react';

interface UseApiOptions {
  /** Polling interval in ms. 0 = no polling (default). */
  pollInterval?: number;
}

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Generic data-fetching hook with optional polling.
 *
 * Replaces manual useState + useEffect + cancelled-flag patterns.
 * When `pollInterval` > 0, re-fetches on that interval until unmount.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: any[] = [],
  options: UseApiOptions = {},
): UseApiState<T> {
  const { pollInterval = 0 } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refetchTrigger, setRefetchTrigger] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const doFetch = async (isInitial: boolean) => {
      try {
        if (isInitial) setLoading(true);
        setError(null);
        const result = await fetcher();
        if (mountedRef.current) {
          setData(result);
        }
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (mountedRef.current && isInitial) {
          setLoading(false);
        }
      }
    };

    doFetch(true);

    if (pollInterval > 0) {
      intervalId = setInterval(() => doFetch(false), pollInterval);
    }

    return () => {
      mountedRef.current = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [...deps, refetchTrigger, pollInterval]);

  const refetch = useCallback(() => setRefetchTrigger((prev) => prev + 1), []);

  return { data, loading, error, refetch };
}
