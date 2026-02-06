# FRONTEND AUDIT REPORT - QLTS

**Date:** 2025-01-27
**Auditor:** Claude
**Reference Systems:** Linear (efficiency) + Notion (warmth)

---

## 1. INVENTORY

| Category | Count |
|----------|-------|
| Component files (`/src/components`) | 187 |
| Page files (`/src/app`) | 140 |
| **Total .tsx files** | **327** |
| UI components (`/components/ui`) | 40 |
| Custom components | 147 |
| CSS token files | 6 |
| Theme files | 2 (light, dark) |

### Directory Structure
```
src/
├── app/           # Next.js App Router (140 files)
├── components/
│   ├── ui/        # shadcn/ui base (40 files)
│   ├── admin/     # Admin-specific
│   ├── admission/ # Admission flows
│   ├── audit/     # Audit log
│   ├── common/    # Shared components
│   ├── forms/     # Form components
│   ├── layouts/   # Layout components
│   ├── leads/     # Lead management
│   ├── notifications/
│   └── officer/   # Officer dashboard
├── hooks/         # React Query hooks
├── lib/           # Utils, API, stores
├── styles/
│   ├── tokens/    # Design tokens (foundation, semantic, admission, components)
│   ├── themes/    # Light & dark themes
│   └── globals.css
└── types/         # TypeScript definitions
```

---

## 2. CURRENT STATE vs TARGET

### 2.1 Colors

| Aspect | Current | Target (Linear+Notion) | Gap |
|--------|---------|------------------------|-----|
| Color Space | OKLCH (modern) | HSL/Hex (warm gray) | 🟡 Consider migration |
| Gray Palette | Cool blue-tinted (hue ~265) | Warm stone (Notion-style) | ❌ **Critical** |
| Primary | Blue (oklch 0.208) | Blue (#3b82f6) | ✅ OK (similar) |
| Semantic colors | CSS variables | CSS variables | ✅ OK |
| Hardcoded colors | 74+ instances | Should be 0 | ❌ **High priority** |

**Hardcoded Color Instances Found:**
- `text-red-600` / `text-red-500`: 74 uses
- `text-green-600`: 37 uses
- `text-blue-600`: 25 uses
- `bg-red-100` / `bg-green-100` / `bg-blue-100`: 62 uses combined
- `text-amber-600`: 18 uses

### 2.2 Typography

| Aspect | Current | Target | Gap |
|--------|---------|--------|-----|
| Font family (body) | Inter | Inter | ✅ OK |
| Font family (display) | Inter | Plus Jakarta Sans | ❌ Missing display font |
| Base font size | 14px (text-sm) | 13px | ❌ Too large for dense UI |
| Most used size | text-sm (411 uses) | text-base (13px) | 🟡 Needs remapping |
| Heading sizes | text-lg, text-2xl | Needs audit | 🟡 Review scale |

**Current Typography Distribution:**
```
text-sm:    411 uses (14px - most common)
text-xs:    341 uses (12px)
text-base:   40 uses (16px)
text-lg:     33 uses (18px)
text-2xl:    26 uses (24px)
```

### 2.3 Spacing

| Aspect | Current | Target | Gap |
|--------|---------|--------|-----|
| Base unit | 4px (good) | 4px | ✅ OK |
| Most used gap | gap-2 (8px) = 288 uses | gap-2 | ✅ OK |
| Card padding | p-6 (24px) | p-4 (16px) | 🟡 Too generous |
| Header padding | p-6 (24px) | p-4 (16px) | 🟡 Too generous |

**Current Spacing Distribution:**
```
gap-2:  288 uses (8px)
gap-1:   90 uses (4px)
gap-4:   69 uses (16px)
gap-3:   52 uses (12px)
p-4:     49 uses
p-3:     48 uses
p-6:     23 uses
```

### 2.4 Border Radius

| Aspect | Current | Target | Gap |
|--------|---------|--------|-----|
| --radius-sm | 0.375rem (6px) | 0.25rem (4px) | ❌ 2px larger |
| --radius-md | 0.5rem (8px) | 0.375rem (6px) | ❌ 2px larger |
| --radius-lg | 0.625rem (10px) | 0.5rem (8px) | ❌ 2px larger |
| --radius-xl | 0.75rem (12px) | 0.75rem (12px) | ✅ OK |

**Current Usage:**
```
rounded-full: 103 uses (badges, avatars)
rounded-lg:    79 uses
rounded-md:    66 uses
rounded:       40 uses
rounded-sm:    13 uses
```

### 2.5 Animations

| Aspect | Current | Target | Gap |
|--------|---------|--------|-----|
| --duration-fast | 150ms | 100ms | ❌ 50ms slower |
| --duration-normal | 200ms | 150ms | ❌ 50ms slower |
| --duration-slow | 300ms | 200ms | ❌ 100ms slower |
| Easing | cubic-bezier(0.4,0,0.2,1) | Same | ✅ OK |

### 2.6 Shadows

| Aspect | Current | Target | Gap |
|--------|---------|--------|-----|
| shadow-sm | Standard Tailwind | Softer (Notion-style) | 🟡 Could be softer |
| shadow-md | Standard Tailwind | Softer | 🟡 Could be softer |
| shadow-lg | Standard Tailwind | Softer | 🟡 Could be softer |

---

## 3. ISSUES BY SEVERITY

### 🔴 Critical (Ảnh hưởng UX nghiêm trọng)

#### 3.1 Cool Gray Palette (Current: Blue-tinted)
**Impact:** Gây mỏi mắt khi sử dụng lâu, thiếu sự ấm áp
**Files affected:** `/styles/themes/light.css`, `/styles/themes/dark.css`
**Solution:** Migrate from OKLCH hue ~265 (blue) to warm stone grays

#### 3.2 Hardcoded Colors (74+ instances)
**Impact:** Không nhất quán, khó maintain, accessibility issues
**Files affected:** ~50+ component files
**Solution:** Create semantic color tokens (success, warning, error) and migrate

### 🟡 High (Nên fix sớm)

#### 3.3 Typography Too Large for Dense UI
**Impact:** Giảm information density, không phù hợp CRM
**Files affected:** All components using text-sm as base
**Solution:** Remap Tailwind font-size scale

#### 3.4 Missing Display Font
**Impact:** Headings thiếu personality
**Files affected:** Heading components, titles
**Solution:** Add Plus Jakarta Sans for headings

#### 3.5 Border Radius Too Large
**Impact:** Less professional, less Linear-like
**Files affected:** `/styles/tokens/foundation.css`
**Solution:** Reduce all radius by ~2px

#### 3.6 Animation Too Slow
**Impact:** UI feels sluggish vs Linear's snappy feel
**Files affected:** `/styles/tokens/foundation.css`
**Solution:** Reduce durations by 50ms across the board

### 🟢 Medium (Fix khi có thời gian)

#### 3.7 Card Padding Too Generous
**Impact:** Wasted space, less dense
**Files affected:** `/components/ui/card.tsx`
**Solution:** Reduce from p-6 to p-4 or p-3

#### 3.8 Shadows Could Be Softer
**Impact:** Less Notion-like warmth
**Files affected:** `/styles/tokens/foundation.css`
**Solution:** Reduce shadow opacity

#### 3.9 Input Height Could Be Smaller
**Impact:** Forms take more space
**Files affected:** `/components/ui/input.tsx`
**Solution:** Consider h-8 instead of h-9

---

## 4. COMPONENT AUDIT

### Button (`/components/ui/button.tsx`)
| Aspect | Status | Notes |
|--------|--------|-------|
| Variants | ✅ 6 variants | default, destructive, outline, secondary, ghost, link |
| Sizes | ✅ 6 sizes | default (h-9), sm (h-8), lg (h-10), icon variants |
| Focus states | ✅ Good | Using ring-based focus |
| Disabled states | ✅ Good | opacity-50, pointer-events-none |
| **Issues** | 🟡 | Could add "danger" variant alias |

### Input (`/components/ui/input.tsx`)
| Aspect | Status | Notes |
|--------|--------|-------|
| Height | 🟡 h-9 (36px) | Could be h-8 (32px) for dense UI |
| Border | ✅ Good | Using border-input token |
| Focus | ✅ Good | ring-1 on focus |
| **Issues** | 🟡 | text-base on mobile, text-sm on desktop - inconsistent |

### Card (`/components/ui/card.tsx`)
| Aspect | Status | Notes |
|--------|--------|-------|
| Border radius | 🟡 rounded-xl | Could be rounded-lg for Linear-style |
| Padding | 🟡 p-6 (24px) | Too generous, should be p-4 |
| Shadow | ✅ shadow | Standard shadow |
| **Issues** | ❌ | CardHeader/CardContent both use p-6 = 48px total vertical |

### Badge (`/components/ui/badge.tsx`)
| Aspect | Status | Notes |
|--------|--------|-------|
| Variants | ✅ 4 variants | default, secondary, destructive, outline |
| Size | ✅ Good | px-2.5 py-0.5, text-xs |
| Border radius | ✅ rounded-md | Good |
| **Issues** | 🟡 | Missing success/warning variants |

### Table (`/components/ui/table.tsx`)
| Aspect | Status | Notes |
|--------|--------|-------|
| Density | 🟡 | Standard density, could be denser |
| Borders | ✅ | Using border-b |
| **Issues** | 🟡 | Row height could be reduced |

### Select (`/components/ui/select.tsx`)
| Aspect | Status | Notes |
|--------|--------|-------|
| Height | ✅ h-9 | Consistent with Input |
| Styling | ✅ Good | Well-styled dropdown |
| **Issues** | None | |

---

## 5. POSITIVE FINDINGS

### ✅ Already Good
1. **Token System Architecture** - Well-organized CSS variables structure
2. **OKLCH Color Space** - Modern, perceptually uniform (just needs warm hues)
3. **Dark Mode Support** - Full dark theme with separate file
4. **QLTS-specific Tokens** - Admission status, lead pipeline, score colors
5. **shadcn/ui Foundation** - Solid, accessible base components
6. **React Query Integration** - Good data fetching patterns
7. **TypeScript** - Full type coverage
8. **Tailwind v3** - Modern configuration
9. **Component Organization** - Clear separation of concerns
10. **Animation Utilities** - Custom keyframes defined

---

## 6. RECOMMENDATIONS SUMMARY

### Immediate Actions (Week 1)
1. ✅ Update gray palette from cool to warm (stone)
2. ✅ Create semantic color tokens (success, warning, error, info)
3. ✅ Reduce animation durations
4. ✅ Reduce border radius scale

### Short-term (Week 2-3)
1. Add Plus Jakarta Sans display font
2. Remap typography scale for dense UI
3. Migrate hardcoded colors to tokens
4. Update Card component (reduce padding)

### Medium-term (Week 4+)
1. Audit all screens for consistency
2. Create component variants for dense mode
3. Add keyboard shortcuts (Linear-style)
4. Performance audit (bundle size, render times)

---

## 7. METRICS

| Metric | Current | Target | Priority |
|--------|---------|--------|----------|
| Hardcoded colors | 74+ | 0 | High |
| Components using semantic tokens | ~70% | 100% | High |
| Dense UI compliance | ~60% | 90%+ | Medium |
| Animation snappiness | 200ms avg | 150ms avg | Medium |
| Accessibility score | Unknown | WCAG AA | High |

---

## APPENDIX: Files to Modify

### Foundation (3 files)
- `src/styles/tokens/foundation.css`
- `src/styles/themes/light.css`
- `src/styles/themes/dark.css`

### Config (2 files)
- `tailwind.config.ts`
- `src/app/layout.tsx` (fonts)

### Core Components (10 files)
- `src/components/ui/button.tsx`
- `src/components/ui/input.tsx`
- `src/components/ui/card.tsx`
- `src/components/ui/badge.tsx`
- `src/components/ui/select.tsx`
- `src/components/ui/table.tsx`
- `src/components/ui/dialog.tsx`
- `src/components/ui/tabs.tsx`
- `src/components/ui/dropdown-menu.tsx`
- `src/components/ui/popover.tsx`

### High-traffic Screens (5 files)
- Lead List page
- Lead Detail page
- Dashboard
- Pipeline Board
- Admission pages
