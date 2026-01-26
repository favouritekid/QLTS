// tailwind.config.ts - V3-style stable config for Next 16 + Turbopack
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
        mono: ["var(--font-mono)"],
      },

      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
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
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },

  plugins: [animatePlugin],
} satisfies Config;

export default config;
