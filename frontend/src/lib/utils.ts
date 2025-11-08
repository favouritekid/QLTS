// src/lib/utils.ts
/**
 * Utility functions for the application
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { API_BASE_URL } from "@/lib/api/client";

/**
 * Merge class names with Tailwind CSS
 * Combines clsx and tailwind-merge for optimal class name handling
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Convert relative avatar URL to absolute URL with backend base URL
 * This is necessary because Next.js dev server runs on different port than FastAPI
 * @param avatarUrl - The avatar URL from backend (can be relative or absolute)
 * @returns Absolute URL pointing to backend server or empty string
 */
export function getAvatarUrl(avatarUrl?: string | null): string {
  if (!avatarUrl) return "";

  // If already absolute URL, return as is
  if (avatarUrl.startsWith("http://") || avatarUrl.startsWith("https://")) {
    return avatarUrl;
  }

  // Convert relative URL to absolute using backend base URL
  // Remove leading slash if present to avoid double slashes
  const cleanPath = avatarUrl.startsWith("/") ? avatarUrl.slice(1) : avatarUrl;
  return `${API_BASE_URL}/${cleanPath}`;
}
