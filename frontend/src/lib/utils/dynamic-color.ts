// src/lib/utils/dynamic-color.ts
/**
 * Dynamic Color System for Dark Mode Support
 *
 * Handles colors from database/API that need to work in both light and dark modes.
 * Provides utilities for:
 * - Color parsing and conversion
 * - Automatic dark mode adjustments
 * - Contrast-aware text colors
 * - CSS variable fallbacks
 */

// =============================================================================
// TYPES
// =============================================================================

export interface RGB {
  r: number;
  g: number;
  b: number;
}

export interface HSL {
  h: number;
  s: number;
  l: number;
}

export interface DynamicColorOptions {
  /** Fallback color if input is invalid */
  fallback?: string;
  /** Adjust color for dark mode (lighter/more saturated) */
  darkModeAdjust?: boolean;
  /** Target lightness for dark mode (0-100) */
  darkModeLightness?: number;
}

// =============================================================================
// COLOR PARSING
// =============================================================================

/**
 * Parse hex color to RGB
 */
export function hexToRgb(hex: string): RGB | null {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) {
    // Try 3-digit hex
    const short = /^#?([a-f\d])([a-f\d])([a-f\d])$/i.exec(hex);
    if (!short) return null;
    return {
      r: parseInt(short[1] + short[1], 16),
      g: parseInt(short[2] + short[2], 16),
      b: parseInt(short[3] + short[3], 16),
    };
  }
  return {
    r: parseInt(result[1], 16),
    g: parseInt(result[2], 16),
    b: parseInt(result[3], 16),
  };
}

/**
 * Convert RGB to hex
 */
export function rgbToHex({ r, g, b }: RGB): string {
  return `#${[r, g, b].map(x => x.toString(16).padStart(2, '0')).join('')}`;
}

/**
 * Convert RGB to HSL
 */
export function rgbToHsl({ r, g, b }: RGB): HSL {
  r /= 255;
  g /= 255;
  b /= 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }

  return { h: h * 360, s: s * 100, l: l * 100 };
}

/**
 * Convert HSL to RGB
 */
export function hslToRgb({ h, s, l }: HSL): RGB {
  h /= 360;
  s /= 100;
  l /= 100;

  let r, g, b;

  if (s === 0) {
    r = g = b = l;
  } else {
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    };

    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }

  return {
    r: Math.round(r * 255),
    g: Math.round(g * 255),
    b: Math.round(b * 255),
  };
}

// =============================================================================
// COLOR MANIPULATION
// =============================================================================

/**
 * Calculate relative luminance (WCAG)
 */
export function getLuminance({ r, g, b }: RGB): number {
  const [rs, gs, bs] = [r, g, b].map(c => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

/**
 * Calculate contrast ratio between two colors
 */
export function getContrastRatio(color1: RGB, color2: RGB): number {
  const l1 = getLuminance(color1);
  const l2 = getLuminance(color2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * Determine if text should be light or dark based on background
 */
export function getContrastTextColor(bgColor: string): "light" | "dark" {
  const rgb = hexToRgb(bgColor);
  if (!rgb) return "dark";

  const luminance = getLuminance(rgb);
  // Use 0.179 threshold (Web Content Accessibility Guidelines)
  return luminance > 0.179 ? "dark" : "light";
}

/**
 * Adjust color lightness for dark mode
 * Makes colors lighter and slightly more saturated for dark backgrounds
 */
export function adjustForDarkMode(color: string, targetLightness = 65): string {
  const rgb = hexToRgb(color);
  if (!rgb) return color;

  const hsl = rgbToHsl(rgb);

  // If already light enough, don't adjust
  if (hsl.l >= targetLightness) return color;

  // Increase lightness and slightly boost saturation
  const adjusted: HSL = {
    h: hsl.h,
    s: Math.min(hsl.s * 1.1, 100), // Boost saturation by 10%
    l: targetLightness,
  };

  return rgbToHex(hslToRgb(adjusted));
}

/**
 * Create a muted/pastel version of a color for backgrounds
 */
export function createMutedBackground(color: string, lightMode = true): string {
  const rgb = hexToRgb(color);
  if (!rgb) return color;

  const hsl = rgbToHsl(rgb);

  const adjusted: HSL = lightMode
    ? { h: hsl.h, s: Math.min(hsl.s * 0.4, 40), l: 95 } // Light: very light pastel
    : { h: hsl.h, s: Math.min(hsl.s * 0.5, 50), l: 15 }; // Dark: dark muted

  return rgbToHex(hslToRgb(adjusted));
}

// =============================================================================
// DYNAMIC COLOR STYLES
// =============================================================================

/**
 * Default fallback color (gray-500)
 */
export const DEFAULT_COLOR = "#6B7280";

/**
 * Stage colors mapping (can be overridden by API)
 */
export const STAGE_COLORS: Record<string, string> = {
  new: "#3B82F6",      // blue-500
  contacted: "#8B5CF6", // violet-500
  qualified: "#F59E0B", // amber-500
  proposal: "#EC4899",  // pink-500
  negotiation: "#6366F1", // indigo-500
  won: "#10B981",      // emerald-500
  lost: "#EF4444",     // red-500
};

/**
 * Generate inline styles for dynamic color with dark mode support
 *
 * @example
 * ```tsx
 * <div style={getDynamicColorStyle(status.color_code, isDarkMode)} />
 * ```
 */
export function getDynamicColorStyle(
  color: string | null | undefined,
  isDarkMode: boolean,
  options: DynamicColorOptions = {}
): React.CSSProperties {
  const {
    fallback = DEFAULT_COLOR,
    darkModeAdjust = true,
    darkModeLightness = 65,
  } = options;

  let safeColor = sanitizeColor(color, fallback);

  if (isDarkMode && darkModeAdjust) {
    safeColor = adjustForDarkMode(safeColor, darkModeLightness);
  }

  return { backgroundColor: safeColor };
}

/**
 * Generate styles for badge with dynamic color
 * Includes background and appropriate text color
 */
export function getDynamicBadgeStyle(
  color: string | null | undefined,
  isDarkMode: boolean,
  options: DynamicColorOptions = {}
): React.CSSProperties {
  const {
    fallback = DEFAULT_COLOR,
    darkModeAdjust = true,
  } = options;

  const bgColor = sanitizeColor(color, fallback);

  if (isDarkMode && darkModeAdjust) {
    // For dark mode: use muted background, brighter text
    const mutedBg = createMutedBackground(bgColor, false);
    const textColor = adjustForDarkMode(bgColor, 70);
    return {
      backgroundColor: mutedBg,
      color: textColor,
      borderColor: textColor,
    };
  }

  // Light mode: use muted background, darker text
  const mutedBg = createMutedBackground(bgColor, true);
  const textColor = adjustForDarkMode(bgColor, 35);
  return {
    backgroundColor: mutedBg,
    color: textColor,
    borderColor: textColor,
  };
}

/**
 * Generate styles for solid badge (colored background)
 */
export function getDynamicSolidBadgeStyle(
  color: string | null | undefined,
  isDarkMode: boolean,
  options: DynamicColorOptions = {}
): React.CSSProperties {
  const { fallback = DEFAULT_COLOR } = options;

  let bgColor = sanitizeColor(color, fallback);

  if (isDarkMode) {
    bgColor = adjustForDarkMode(bgColor, 55);
  }

  const textContrast = getContrastTextColor(bgColor);

  return {
    backgroundColor: bgColor,
    color: textContrast === "light" ? "#FFFFFF" : "#1F2937",
  };
}

/**
 * Generate CSS variable with fallback
 */
export function colorVar(name: string, fallback = DEFAULT_COLOR): string {
  return `var(--color-${name}, ${fallback})`;
}

// =============================================================================
// SANITIZATION (re-export from utils.ts for convenience)
// =============================================================================

/**
 * Sanitize color code (simplified version, full version in utils.ts)
 */
export function sanitizeColor(
  color: string | null | undefined,
  fallback = DEFAULT_COLOR
): string {
  if (!color || typeof color !== "string") return fallback;

  const trimmed = color.trim();

  // Hex colors
  if (/^#(?:[0-9A-Fa-f]{3}){1,2}(?:[0-9A-Fa-f]{2})?$/.test(trimmed)) {
    return trimmed;
  }

  // RGB/RGBA
  if (/^rgba?\(.+\)$/.test(trimmed)) {
    return trimmed;
  }

  return fallback;
}
