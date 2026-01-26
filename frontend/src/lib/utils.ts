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
 * Sanitize CSS color code to prevent XSS attacks
 * Only allows valid CSS color formats: hex, rgb, rgba, hsl, hsla, named colors
 *
 * ⚠️ SECURITY: Never pass unsanitized user input directly to style attributes
 *
 * @param colorCode - The color code from backend
 * @param fallback - Fallback color if invalid (default: "#6B7280" gray-500)
 * @returns Safe CSS color string
 */
export function sanitizeColorCode(
  colorCode: string | null | undefined,
  fallback: string = "#6B7280"
): string {
  if (!colorCode || typeof colorCode !== "string") {
    return fallback;
  }

  const trimmed = colorCode.trim();

  // Hex colors: #RGB, #RRGGBB, #RRGGBBAA
  if (/^#(?:[0-9A-Fa-f]{3}){1,2}(?:[0-9A-Fa-f]{2})?$/.test(trimmed)) {
    return trimmed;
  }

  // RGB/RGBA: rgb(r, g, b) or rgba(r, g, b, a)
  if (/^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/.test(trimmed)) {
    return trimmed;
  }

  // HSL/HSLA: hsl(h, s%, l%) or hsla(h, s%, l%, a)
  if (/^hsla?\(\s*\d{1,3}\s*,\s*\d{1,3}%\s*,\s*\d{1,3}%\s*(?:,\s*(?:0|1|0?\.\d+)\s*)?\)$/.test(trimmed)) {
    return trimmed;
  }

  // Named CSS colors (common subset for performance)
  const namedColors = new Set([
    "transparent", "inherit", "currentcolor",
    "black", "white", "red", "green", "blue", "yellow", "orange", "purple",
    "pink", "gray", "grey", "cyan", "magenta", "lime", "maroon", "navy",
    "olive", "teal", "aqua", "fuchsia", "silver"
  ]);

  if (namedColors.has(trimmed.toLowerCase())) {
    return trimmed.toLowerCase();
  }

  // Invalid color - return fallback
  return fallback;
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
