import { useState, useEffect, useCallback } from "react";

/**
 * Countdown timer hook for rate limit UX.
 *
 * Reads Retry-After header from 429 responses, falls back to defaultSeconds.
 * Auto-decrements every second and calls onComplete when reaching 0.
 */
export function useCountdown(defaultSeconds = 60) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    if (seconds <= 0) return;

    const timer = setInterval(() => {
      setSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [seconds]);

  const start = useCallback(
    (retryAfterHeader?: string | null) => {
      const parsed = retryAfterHeader ? parseInt(retryAfterHeader, 10) : NaN;
      setSeconds(Number.isFinite(parsed) && parsed > 0 ? parsed : defaultSeconds);
    },
    [defaultSeconds],
  );

  const reset = useCallback(() => {
    setSeconds(0);
  }, []);

  return {
    seconds,
    isActive: seconds > 0,
    start,
    reset,
  };
}
