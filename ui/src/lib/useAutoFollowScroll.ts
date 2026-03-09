"use client";

import { useCallback, useRef } from "react";

export function useAutoFollowScroll() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFollowRef = useRef(true);
  const metricsRef = useRef({ scrollHeight: 0, scrollTop: 0 });

  const syncScrollPosition = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;

    const previous = metricsRef.current;
    const nextScrollHeight = container.scrollHeight;
    const heightDelta = nextScrollHeight - previous.scrollHeight;

    if (autoFollowRef.current || previous.scrollHeight === 0) {
      container.scrollTop = nextScrollHeight;
      autoFollowRef.current = true;
    } else if (heightDelta > 0) {
      container.scrollTop = previous.scrollTop + heightDelta;
    }

    metricsRef.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    };
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

  return { scrollRef, handleScroll, syncScrollPosition };
}
