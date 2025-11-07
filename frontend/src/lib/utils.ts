// src/lib/utils.ts
/**
 * Utility functions for the application
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names with Tailwind CSS
 * Combines clsx and tailwind-merge for optimal class name handling
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Add cache-busting timestamp to avatar URL to prevent browser caching
 * @param avatarUrl - The avatar URL (can be null/undefined)
 * @param timestamp - Optional timestamp (defaults to current time)
 * @returns URL with cache-busting parameter or empty string
 */
export function getAvatarUrl(avatarUrl?: string | null, timestamp?: number): string {
  if (!avatarUrl) return "";

  try {
    const url = new URL(avatarUrl, window.location.origin);
    url.searchParams.set("t", (timestamp || Date.now()).toString());
    return url.toString();
  } catch {
    // If URL parsing fails, append timestamp as query param
    const separator = avatarUrl.includes("?") ? "&" : "?";
    return `${avatarUrl}${separator}t=${timestamp || Date.now()}`;
  }
}
