"use client";

import { useState, useEffect, useCallback } from "react";

export function usePolling<T>(
  url: string | null,
  intervalMs: number = 3000,
  initialValue: T,
  onData?: (data: T) => void
): { data: T; loading: boolean; error: string | null; refresh: () => void } {
  const [data, setData] = useState<T>(initialValue);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!url) return;
    fetch(url)
      .then(async (r) => {
        const payload = await r.json();
        if (!r.ok) {
          const message =
            payload && typeof payload.error === "string"
              ? payload.error
              : `Request failed with status ${r.status}`;
          throw new Error(message);
        }
        return payload as T;
      })
      .then((d) => {
        setData(d);
        setError(null);
        onData?.(d);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, [url, onData]);

  useEffect(() => {
    if (!url) return;
    refresh();
    const interval = setInterval(refresh, intervalMs);
    return () => clearInterval(interval);
  }, [url, intervalMs, refresh]);

  return { data, loading, error, refresh };
}
