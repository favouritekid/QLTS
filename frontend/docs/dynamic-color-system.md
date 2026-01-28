# Dynamic Color System

**Created:** January 28, 2026
**Purpose:** Handle database-driven colors with dark mode support

---

## Overview

The Dynamic Color System provides utilities for handling colors from the API/database (status colors, stage colors) that need to work correctly in both light and dark modes.

## Problem Statement

Many UI elements display colors from the database:
- Pipeline stage colors (`stage.color_code`)
- Consultation status colors (`status.color_code`)
- Custom user-defined colors

These cannot use Tailwind classes because they're dynamic at runtime. The previous approach used inline styles which broke in dark mode.

---

## Architecture

```
src/
├── lib/utils/
│   ├── dynamic-color.ts    # Color manipulation utilities
│   └── index.ts            # Exports
├── hooks/
│   └── useTheme.ts         # Theme state hook
├── components/ui/
│   └── dynamic-color-badge.tsx  # Ready-to-use badge component
└── styles/tokens/
    └── semantic.css        # Fallback color variables
```

---

## Usage Guide

### 1. DynamicColorBadge Component (Recommended)

The easiest way to display dynamic colors:

```tsx
import { DynamicColorBadge } from "@/components/ui/dynamic-color-badge";

// Basic usage
<DynamicColorBadge color={status.color_code}>
  {status.name}
</DynamicColorBadge>

// With dot indicator
<DynamicColorBadge color={status.color_code} variant="dot">
  {status.name}
</DynamicColorBadge>

// Solid background
<DynamicColorBadge color={stage.color_code} variant="solid">
  {stage.name}
</DynamicColorBadge>

// Outline style
<DynamicColorBadge color={status.color_code} variant="outline">
  {status.name}
</DynamicColorBadge>
```

**Variants:**
| Variant | Description |
|---------|-------------|
| `subtle` | Muted background, colored text (default) |
| `solid` | Colored background, contrast text |
| `outline` | Transparent with colored border |
| `dot` | Neutral with colored dot indicator |

### 2. Utility Functions (Advanced)

For custom implementations:

```tsx
import {
  getDynamicColorStyle,
  getDynamicBadgeStyle,
  getDynamicSolidBadgeStyle,
  adjustForDarkMode,
  sanitizeColor,
} from "@/lib/utils/dynamic-color";
import { useTheme } from "@/hooks/useTheme";

function CustomComponent({ color }) {
  const { isDarkMode } = useTheme();

  // Get inline styles with dark mode adjustment
  const style = getDynamicColorStyle(color, isDarkMode);

  return <div style={style}>...</div>;
}
```

### 3. ColorDot Component

For minimal color indicators:

```tsx
import { ColorDot } from "@/components/ui/dynamic-color-badge";

<ColorDot color={status.color_code} size="md" />
```

---

## CSS Variables (Fallbacks)

Defined in `tokens/semantic.css`:

```css
/* Stage Colors */
--color-stage-new: var(--info-500);
--color-stage-contacted: var(--purple-500);
--color-stage-qualified: var(--warning-500);
--color-stage-won: var(--success-500);
--color-stage-lost: var(--error-500);
--color-stage-default: var(--gray-500);

/* Status Colors */
--color-status-default: var(--gray-500);
--color-status-pending: var(--warning-500);
--color-status-success: var(--success-500);
--color-status-error: var(--error-500);
```

---

## Dark Mode Behavior

The system automatically:
1. **Increases lightness** for dark backgrounds
2. **Boosts saturation** slightly for visibility
3. **Creates muted backgrounds** for badge variants
4. **Ensures text contrast** (WCAG compliant)

### Before/After Example

| Light Mode | Dark Mode |
|------------|-----------|
| `#3B82F6` (blue-500) | `#60A5FA` (lighter blue) |
| Background: `#EFF6FF` | Background: `#1E3A5F` |
| Text: `#1E40AF` | Text: `#93C5FD` |

---

## Migration Guide

### From Inline Styles

```tsx
// Before
<Badge
  style={{
    backgroundColor: status.color_code || "#6b7280",
    color: getContrastColor(status.color_code),
  }}
>
  {status.name}
</Badge>

// After
<DynamicColorBadge color={status.color_code}>
  {status.name}
</DynamicColorBadge>
```

### From Hardcoded Fallbacks

```tsx
// Before
style={{ backgroundColor: color || "#6B7280" }}

// After
import { DEFAULT_COLOR } from "@/lib/utils/dynamic-color";
// or use DynamicColorBadge which handles fallback automatically
```

---

## Files Using Dynamic Colors

Components that display database colors (using this system):

| Component | Color Source | Status |
|-----------|--------------|--------|
| `LeadDetailPanel.tsx` | `consultation_status.color_code` | ✅ Migrated |
| `LeadCard.tsx` | `consultation_status.color_code` | ✅ Migrated |
| `LeadFilterBar.tsx` | `STAGE_COLORS[stage.id]` | ✅ Migrated |
| `LeadsTable.tsx` | `status.color_code` | ✅ Migrated |
| `LeadFilters.tsx` | `STAGE_COLORS[stage.id]` | ✅ Migrated |
| `BulkStageDialog.tsx` | `STAGE_COLORS[stage.id]` | ✅ Migrated |
| `PipelineClient.tsx` | `status.color_code` | ✅ Migrated |
| `TransitionMatrix.tsx` | `status.color_code` | ✅ Migrated |
| `QuickConsultationSection.tsx` | `status.color_code` | ✅ Migrated |
| `LeadInfoTabs.tsx` | `statusColor` | ✅ Migrated |
| `LeadSidebar.tsx` | `consultation_status.color_code` | ✅ Migrated |
| `FunnelChart.tsx` | HSL computed colors | ⚪ Acceptable (chart visualization) |

---

## Best Practices

1. **Use DynamicColorBadge** for status/stage indicators
2. **Don't hardcode fallback colors** - use `DEFAULT_COLOR` constant
3. **Always sanitize** colors from API using `sanitizeColor()`
4. **Test in both themes** - toggle between light and dark modes
5. **Color picker UIs are exceptions** - inline styles acceptable for real-time preview

---

## API Reference

### `sanitizeColor(color, fallback)`
Validates and sanitizes color codes to prevent XSS.

### `adjustForDarkMode(color, targetLightness)`
Adjusts color lightness for dark backgrounds.

### `getDynamicColorStyle(color, isDarkMode, options)`
Returns `React.CSSProperties` with `backgroundColor`.

### `getDynamicBadgeStyle(color, isDarkMode, options)`
Returns styles for muted badge (background, color, border).

### `getDynamicSolidBadgeStyle(color, isDarkMode, options)`
Returns styles for solid badge with contrast text.

### `getContrastTextColor(bgColor)`
Returns `"light"` or `"dark"` for optimal text contrast.

---

*Part of QLTS Frontend Design System v3.1*
