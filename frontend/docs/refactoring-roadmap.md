# FRONTEND REFACTORING ROADMAP - QLTS

**Date:** 2025-01-27
**Reference Systems:** Linear (efficiency) + Notion (warmth)
**Status:** Phase 5 In Progress - Color Migration Started

---

## COMPLETED PHASES

### Phase 1: Explore Codebase
- Inventoried 327 .tsx files (187 components + 140 pages)
- Analyzed current token architecture
- Identified gaps vs target design system

### Phase 2: Create Audit Report
- Created `frontend/docs/audit-report.md`
- Documented all issues by severity
- Identified 74+ hardcoded color instances (actual count: ~420)

### Phase 3: Create Design Tokens Target
- Created `frontend/docs/design-tokens-target.css`
- Defined target state for all tokens

### Phase 4: Update Token System
Files updated:
- `src/styles/tokens/foundation.css` - Tighter radius, faster animations, softer shadows
- `src/styles/themes/light.css` - Warm gray palette (stone) + semantic colors
- `src/styles/themes/dark.css` - Warm gray palette (dark mode)
- `tailwind.config.ts` - Dense typography, semantic colors, animation timing

### Phase 5: Migrate Hardcoded Colors (STARTED)

**Files Migrated (8 files):**
1. `src/components/common/status/StatusBadge.tsx` - success/warning/error/info
2. `src/components/common/UrgencyBadge.tsx` - error/warning/success
3. `src/components/common/ActivityIndicator.tsx` - error/success/info/warning
4. `src/components/audit/AuditLogTimeline.tsx` - success/info/error/warning
5. `src/components/officer/dashboard/KPICard.tsx` - success/error
6. `src/components/officer/dashboard/WeeklyLeaderboard.tsx` - success/error/info
7. `src/components/officer/dashboard/AnnualProgressCard.tsx` - success/info/warning/error
8. `src/components/leads/LeadCard.tsx` - error/warning/info/success

---

## IN PROGRESS

### Phase 5: Remaining Color Migration

**Goal:** Replace ~412 remaining hardcoded Tailwind color classes with semantic tokens

#### 5.1 Color Mapping Table

| Current (Hardcoded) | Replacement (Semantic) | Files Affected |
|---------------------|------------------------|----------------|
| `text-red-600` | `text-error-600` or `text-destructive` | ~30 files |
| `text-red-500` | `text-error-500` | ~20 files |
| `bg-red-100` | `bg-error-50` or `bg-error-100` | ~15 files |
| `text-green-600` | `text-success-600` | ~20 files |
| `bg-green-100` | `bg-success-50` or `bg-success-100` | ~15 files |
| `text-blue-600` | `text-info-600` or `text-primary` | ~15 files |
| `bg-blue-100` | `bg-info-50` or `bg-primary-50` | ~10 files |
| `text-amber-600` | `text-warning-600` | ~10 files |
| `bg-amber-100` | `bg-warning-50` or `bg-warning-100` | ~8 files |

#### 5.2 Migration Commands (Find & Replace)

```bash
# Red to Error/Destructive
grep -rn "text-red-" src/
grep -rn "bg-red-" src/
grep -rn "border-red-" src/

# Green to Success
grep -rn "text-green-" src/
grep -rn "bg-green-" src/
grep -rn "border-green-" src/

# Amber to Warning
grep -rn "text-amber-" src/
grep -rn "bg-amber-" src/
grep -rn "border-amber-" src/
```

#### 5.3 Suggested Order of Migration

1. **Badge components** - Most consistent usage pattern
2. **Alert/Toast components** - Clear semantic meaning
3. **Form validation states** - Error messages, success feedback
4. **Status indicators** - Lead status, admission status
5. **Table row highlights** - Conditional styling

---

### Phase 6: Update Core UI Components

**Goal:** Apply dense UI patterns to shadcn/ui components

#### 6.1 Button (`src/components/ui/button.tsx`)

Current:
```tsx
const buttonVariants = cva("...", {
  variants: {
    size: {
      default: "h-9 px-4 py-2",  // 36px height
      sm: "h-8 px-3",             // 32px height
      lg: "h-10 px-8",            // 40px height
    },
  },
});
```

Target:
```tsx
const buttonVariants = cva("...", {
  variants: {
    size: {
      default: "h-8 px-3 py-1.5",  // 32px height (Linear-style)
      sm: "h-7 px-2.5",            // 28px height
      lg: "h-9 px-6",              // 36px height
    },
  },
});
```

#### 6.2 Input (`src/components/ui/input.tsx`)

Current:
```tsx
className="h-9 ..."  // 36px
```

Target:
```tsx
className="h-8 ..."  // 32px (Linear-style dense)
```

#### 6.3 Card (`src/components/ui/card.tsx`)

Current:
```tsx
const CardHeader = "p-6 ..."    // 24px padding
const CardContent = "p-6 pt-0"  // 24px horizontal, 0 top
```

Target:
```tsx
const CardHeader = "p-4 ..."    // 16px padding
const CardContent = "p-4 pt-0"  // 16px horizontal
```

#### 6.4 Select (`src/components/ui/select.tsx`)

- Reduce trigger height from h-9 to h-8
- Tighten dropdown item padding

#### 6.5 Table (`src/components/ui/table.tsx`)

- Add compact variant with smaller row height
- Use `--table-row-height-compact` token

---

### Phase 7: Add Display Font

**Goal:** Add Plus Jakarta Sans for headings

#### 7.1 Update `src/app/layout.tsx`

```tsx
import { Inter, Plus_Jakarta_Sans } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
});

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["500", "600", "700"],
});

// In body className:
className={`${inter.variable} ${plusJakarta.variable} font-sans`}
```

#### 7.2 Update Heading Components

Apply `font-display` class to:
- Page titles (`<h1>`)
- Section headers (`<h2>`)
- Card titles
- Modal headers

---

### Phase 8: Screen-by-Screen Audit

**Priority Order (by traffic/importance):**

#### 8.1 Dashboard (HIGH)
- [ ] Update card padding
- [ ] Apply dense typography
- [ ] Migrate hardcoded colors
- [ ] Test dark mode

#### 8.2 Lead List (HIGH)
- [ ] Update table row height
- [ ] Apply warm grays
- [ ] Migrate status badge colors
- [ ] Test filtering/sorting UX

#### 8.3 Lead Detail (HIGH)
- [ ] Update card layouts
- [ ] Apply dense spacing
- [ ] Migrate form colors
- [ ] Test all tabs

#### 8.4 Pipeline Board (MEDIUM)
- [ ] Update card sizes
- [ ] Apply drag-drop UX improvements
- [ ] Migrate status colors

#### 8.5 Admission Pages (MEDIUM)
- [ ] Update form layouts
- [ ] Apply progress indicator styling
- [ ] Migrate validation colors

---

### Phase 9: Testing & QA

#### 9.1 Visual Regression Testing

```bash
# If using Playwright visual comparisons
npm run test:e2e:visual
```

Key screens to capture:
- Dashboard (light + dark)
- Lead list (empty, populated, filtered)
- Lead detail (all tabs)
- Forms (validation states)
- Modals/dialogs

#### 9.2 Accessibility Audit

- [ ] Color contrast (WCAG AA)
- [ ] Focus states visible
- [ ] Keyboard navigation
- [ ] Screen reader compatibility

#### 9.3 Performance Check

- [ ] Bundle size unchanged
- [ ] No rendering regressions
- [ ] Animation smoothness (60fps)

---

## MIGRATION UTILITIES

### Batch Color Migration Script

Create `scripts/migrate-colors.js`:

```javascript
const fs = require('fs');
const path = require('path');
const glob = require('glob');

const colorMappings = {
  // Red → Error
  'text-red-600': 'text-error-600',
  'text-red-500': 'text-error-500',
  'bg-red-100': 'bg-error-100',
  'bg-red-50': 'bg-error-50',
  'border-red-200': 'border-error-200',

  // Green → Success
  'text-green-600': 'text-success-600',
  'text-green-500': 'text-success-500',
  'bg-green-100': 'bg-success-100',
  'bg-green-50': 'bg-success-50',
  'border-green-200': 'border-success-200',

  // Amber → Warning
  'text-amber-600': 'text-warning-600',
  'text-amber-500': 'text-warning-500',
  'bg-amber-100': 'bg-warning-100',
  'bg-amber-50': 'bg-warning-50',
  'border-amber-200': 'border-warning-200',

  // Blue → Info (for non-primary uses)
  'text-blue-600': 'text-info-600',
  'bg-blue-100': 'bg-info-100',
  'bg-blue-50': 'bg-info-50',
};

// ... implementation
```

### CSS Variable Fallback Checker

Verify all CSS variables resolve correctly:

```javascript
// In browser console
const root = document.documentElement;
const styles = getComputedStyle(root);

[
  '--gray-500',
  '--success-500',
  '--warning-500',
  '--error-500',
  '--info-500',
].forEach(varName => {
  console.log(`${varName}: ${styles.getPropertyValue(varName)}`);
});
```

---

## SUCCESS METRICS

| Metric | Before | Target | How to Measure |
|--------|--------|--------|----------------|
| Hardcoded colors | 74+ | 0 | `grep -r "text-red-\|text-green-\|text-amber-" src/` |
| Base font size | 14px | 13px | Inspect body text |
| Button height | 36px | 32px | Inspect default buttons |
| Animation duration | 200ms avg | 150ms avg | Check CSS vars |
| Gray palette | Cool (hue ~265) | Warm (hue ~40) | Visual comparison |
| Dense UI score | ~60% | 90%+ | Manual audit |

---

## ROLLBACK PLAN

If issues arise, revert token files:

```bash
git checkout HEAD~1 -- \
  src/styles/tokens/foundation.css \
  src/styles/themes/light.css \
  src/styles/themes/dark.css \
  tailwind.config.ts
```

---

## APPENDIX: File Modification Checklist

### Token Files (DONE)
- [x] `src/styles/tokens/foundation.css`
- [x] `src/styles/themes/light.css`
- [x] `src/styles/themes/dark.css`
- [x] `tailwind.config.ts`

### Config Files (TODO)
- [ ] `src/app/layout.tsx` (add display font)

### Core UI Components (TODO)
- [ ] `src/components/ui/button.tsx`
- [ ] `src/components/ui/input.tsx`
- [ ] `src/components/ui/card.tsx`
- [ ] `src/components/ui/badge.tsx`
- [ ] `src/components/ui/select.tsx`
- [ ] `src/components/ui/table.tsx`
- [ ] `src/components/ui/dialog.tsx`
- [ ] `src/components/ui/tabs.tsx`
- [ ] `src/components/ui/dropdown-menu.tsx`
- [ ] `src/components/ui/popover.tsx`

### Feature Components (TODO - After Core UI)
- [ ] Lead list components
- [ ] Lead detail components
- [ ] Dashboard components
- [ ] Admission components
- [ ] Form components

---

*Last Updated: 2025-01-27*
