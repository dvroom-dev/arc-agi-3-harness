"use client";

import { useState, useEffect, useCallback } from "react";

export function usePolling<T>(
  url: string | null,
  intervalMs: number = 3000,
  initialValue: T
): { data: T; loading: boolean; refresh: () => void } {
  const [data, setData] = useState<T>(initialValue);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    if (!url) return;
    fetch(url)
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(console.error);
  }, [url]);

  useEffect(() => {
    if (!url) return;
    refresh();
    const interval = setInterval(refresh, intervalMs);
    return () => clearInterval(interval);
  }, [url, intervalMs, refresh]);

  return { data, loading, refresh };
}
