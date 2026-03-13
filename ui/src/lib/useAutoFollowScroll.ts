"use client";

import { useCallback, useRef } from "react";

export function useAutoFollowScroll() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFollowRef = useRef(true);
  const metricsRef = useRef({ scrollHeight: 0, scrollTop: 0 });
  const preserveOffsetOnNextSyncRef = useRef(false);

  const syncScrollPosition = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;

    const previous = metricsRef.current;
    const nextScrollHeight = container.scrollHeight;
    const heightDelta = nextScrollHeight - previous.scrollHeight;

    if (autoFollowRef.current || previous.scrollHeight === 0) {
      container.scrollTop = nextScrollHeight;
      autoFollowRef.current = true;
    } else if (preserveOffsetOnNextSyncRef.current && heightDelta > 0) {
      container.scrollTop = previous.scrollTop + heightDelta;
    } else {
      // Detached from tail: preserve the current viewport when new items append below.
      container.scrollTop = previous.scrollTop;
    }

    metricsRef.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    };
    preserveOffsetOnNextSyncRef.current = false;
  }, []);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;

    const distanceFromBottom =
      container.scrollHeight - container.clientHeight - container.scrollTop;
    autoFollowRef.current = distanceFromBottom <= 24;
    metricsRef.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    };
  }, []);

  const prepareForPrepend = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;

    metricsRef.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    };
    preserveOffsetOnNextSyncRef.current = true;
  }, []);

  return { scrollRef, handleScroll, syncScrollPosition, prepareForPrepend };
}
