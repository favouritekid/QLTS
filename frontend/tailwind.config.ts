// tailwind.config.ts - V3-style stable config for Next 16 + Turbopack
// Reference: Linear efficiency + Notion warmth
// Updated: 2025-01-27
import type { Config } from "tailwindcss";
import animatePlugin from "tailwindcss-animate";

const config: Config = {
  // Content paths - explicit, no auto-detection
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
    "./src/hooks/**/*.{ts,tsx}",
    "./src/types/**/*.{ts,tsx}",
    "./src/constants/**/*.{ts,tsx}",
  ],

  darkMode: ["class"],

  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)"],
        display: ["var(--font-display)"],
        mono: ["var(--font-mono)"],
      },

      // Dense UI font sizes (Linear-style)
      fontSize: {
        "2xs": ["var(--text-2xs)", { lineHeight: "var(--leading-tight)" }],
        xs: ["var(--text-xs)", { lineHeight: "var(--leading-tight)" }],
        sm: ["var(--text-sm)", { lineHeight: "var(--leading-snug)" }],
        base: ["var(--text-base)", { lineHeight: "var(--leading-normal)" }],
        md: ["var(--text-md)", { lineHeight: "var(--leading-normal)" }],
        lg: ["var(--text-lg)", { lineHeight: "var(--leading-snug)" }],
        xl: ["var(--text-xl)", { lineHeight: "var(--leading-tight)" }],
        "2xl": ["var(--text-2xl)", { lineHeight: "var(--leading-tight)" }],
        "3xl": ["var(--text-3xl)", { lineHeight: "var(--leading-none)" }],
      },

      borderRadius: {
        none: "var(--radius-none)",
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
        "2xl": "var(--radius-2xl)",
      },

      // Snappy animation durations (Linear-style)
      transitionDuration: {
        instant: "var(--duration-instant)",
        fast: "var(--duration-fast)",
        normal: "var(--duration-normal)",
        slow: "var(--duration-slow)",
        slower: "var(--duration-slower)",
      },

      // Soft shadows (Notion-style)
      boxShadow: {
        xs: "var(--shadow-xs)",
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        xl: "var(--shadow-xl)",
        primary: "var(--shadow-primary)",
        success: "var(--shadow-success)",
        error: "var(--shadow-error)",
      },

      colors: {
        // Semantic Colors (from CSS variables)
        bg: "var(--color-bg)",
        fg: "var(--color-fg)",
        border: "var(--color-border)",
        input: "var(--color-input)",
        ring: "var(--color-ring)",
        background: "var(--background)",
        foreground: "var(--foreground)",

        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        // Semantic colors (success, warning, error, info)
        success: {
          DEFAULT: "var(--success)",
          foreground: "var(--success-foreground)",
          50: "var(--success-50)",
          100: "var(--success-100)",
          500: "var(--success-500)",
          600: "var(--success-600)",
          700: "var(--success-700)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          foreground: "var(--warning-foreground)",
          50: "var(--warning-50)",
          100: "var(--warning-100)",
          500: "var(--warning-500)",
          600: "var(--warning-600)",
          700: "var(--warning-700)",
        },
        error: {
          DEFAULT: "var(--error-500)",
          50: "var(--error-50)",
          100: "var(--error-100)",
          500: "var(--error-500)",
          600: "var(--error-600)",
          700: "var(--error-700)",
        },
        info: {
          DEFAULT: "var(--info-500)",
          50: "var(--info-50)",
          100: "var(--info-100)",
          500: "var(--info-500)",
          600: "var(--info-600)",
          700: "var(--info-700)",
        },
        // Warm gray scale (stone)
        gray: {
          50: "var(--gray-50)",
          100: "var(--gray-100)",
          200: "var(--gray-200)",
          300: "var(--gray-300)",
          400: "var(--gray-400)",
          500: "var(--gray-500)",
          600: "var(--gray-600)",
          700: "var(--gray-700)",
          800: "var(--gray-800)",
          900: "var(--gray-900)",
          950: "var(--gray-950)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },

        // Sidebar
        sidebar: {
          DEFAULT: "var(--sidebar)",
          foreground: "var(--sidebar-foreground)",
          primary: "var(--sidebar-primary)",
          "primary-foreground": "var(--sidebar-primary-foreground)",
          accent: "var(--sidebar-accent)",
          "accent-foreground": "var(--sidebar-accent-foreground)",
          border: "var(--sidebar-border)",
          ring: "var(--sidebar-ring)",
        },

        // Charts
        chart: {
          "1": "var(--chart-1)",
          "2": "var(--chart-2)",
          "3": "var(--chart-3)",
          "4": "var(--chart-4)",
          "5": "var(--chart-5)",
        },

        // Admission Status Colors (QLTS-specific)
        admission: {
          draft: {
            bg: "var(--admission-draft-bg)",
            fg: "var(--admission-draft-fg)",
            border: "var(--admission-draft-border)",
          },
          submitted: {
            bg: "var(--admission-submitted-bg)",
            fg: "var(--admission-submitted-fg)",
            border: "var(--admission-submitted-border)",
          },
          reviewing: {
            bg: "var(--admission-reviewing-bg)",
            fg: "var(--admission-reviewing-fg)",
            border: "var(--admission-reviewing-border)",
          },
          approved: {
            bg: "var(--admission-approved-bg)",
            fg: "var(--admission-approved-fg)",
            border: "var(--admission-approved-border)",
          },
          rejected: {
            bg: "var(--admission-rejected-bg)",
            fg: "var(--admission-rejected-fg)",
            border: "var(--admission-rejected-border)",
          },
          enrolled: {
            bg: "var(--admission-enrolled-bg)",
            fg: "var(--admission-enrolled-fg)",
            border: "var(--admission-enrolled-border)",
          },
        },

        // Lead Pipeline Colors
        lead: {
          new: {
            bg: "var(--lead-new-bg)",
            fg: "var(--lead-new-fg)",
          },
          contacted: {
            bg: "var(--lead-contacted-bg)",
            fg: "var(--lead-contacted-fg)",
          },
          qualified: {
            bg: "var(--lead-qualified-bg)",
            fg: "var(--lead-qualified-fg)",
          },
          converted: {
            bg: "var(--lead-converted-bg)",
            fg: "var(--lead-converted-fg)",
          },
          lost: {
            bg: "var(--lead-lost-bg)",
            fg: "var(--lead-lost-fg)",
          },
        },

        // Score Indicators
        score: {
          excellent: {
            bg: "var(--score-excellent-bg)",
            fg: "var(--score-excellent-fg)",
          },
          good: {
            bg: "var(--score-good-bg)",
            fg: "var(--score-good-fg)",
          },
          average: {
            bg: "var(--score-average-bg)",
            fg: "var(--score-average-fg)",
          },
          poor: {
            bg: "var(--score-poor-bg)",
            fg: "var(--score-poor-fg)",
          },
        },
      },

      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "fade-out": {
          from: { opacity: "1" },
          to: { opacity: "0" },
        },
        "slide-in-from-top": {
          from: { transform: "translateY(-100%)" },
          to: { transform: "translateY(0)" },
        },
        "slide-in-from-bottom": {
          from: { transform: "translateY(100%)" },
          to: { transform: "translateY(0)" },
        },
        "scale-in": {
          from: { transform: "scale(0.95)", opacity: "0" },
          to: { transform: "scale(1)", opacity: "1" },
        },
      },
      animation: {
        // Snappy durations (Linear-style: 150ms instead of 200ms)
        "accordion-down": "accordion-down 150ms ease-out",
        "accordion-up": "accordion-up 150ms ease-out",
        "fade-in": "fade-in 100ms ease-out",
        "fade-out": "fade-out 100ms ease-in",
        "slide-in-top": "slide-in-from-top 150ms ease-out",
        "slide-in-bottom": "slide-in-from-bottom 150ms ease-out",
        "scale-in": "scale-in 150ms ease-out",
      },
    },
  },

  plugins: [animatePlugin],
} satisfies Config;

export default config;
