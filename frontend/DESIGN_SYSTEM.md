# QLTS Design System Documentation

> **Version:** 3.0
> **Last Updated:** 2026-01-28
> **Philosophy:** Linear efficiency + Notion warmth

---

## Table of Contents

1. [Overview](#overview)
2. [Design Philosophy](#design-philosophy)
3. [Color System](#color-system)
4. [Typography](#typography)
5. [Spacing & Layout](#spacing--layout)
6. [Component Specifications](#component-specifications)
7. [Layout Components](#layout-components)
8. [Icons](#icons)
9. [Animation & Motion](#animation--motion)
10. [Patterns & Best Practices](#patterns--best-practices)

---

## Overview

QLTS Design System is built for a dense, professional UI optimized for data-heavy admin interfaces. It combines the efficiency of Linear with the warmth of Notion.

### Key Characteristics

| Aspect | Specification |
|--------|---------------|
| **Density** | Dense UI - 32px default height for inputs/buttons |
| **Typography** | 13px base font size (smaller than typical 14-16px) |
| **Border Radius** | Tighter radii (4-6px) for professional look |
| **Shadows** | Softer, subtle shadows |
| **Colors** | Semantic color system with light/dark mode support |

### File Structure

```
frontend/src/styles/
├── tokens/
│   ├── colors.css      # Semantic color tokens (light/dark)
│   └── foundation.css  # Spacing, typography, layout tokens
└── globals.css         # Imports and global styles
```

---

## Design Philosophy

### 1. Dense but Readable
- Compact spacing without sacrificing readability
- 32px default component heights (vs typical 40px)
- 13px base text (vs typical 14-16px)

### 2. Semantic Colors Only
- **NEVER** use raw Tailwind colors (`blue-500`, `red-600`)
- **ALWAYS** use semantic tokens (`primary`, `destructive`, `success`)
- Colors adapt automatically to light/dark mode

### 3. Consistency Through Tokens
- All values come from CSS custom properties
- Easy theme customization by changing token values
- Predictable spacing scale (4px base unit)

---

## Color System

### Semantic Color Tokens

Located in `src/styles/tokens/colors.css`

#### Brand Colors

| Token | Light Mode | Dark Mode | Usage |
|-------|------------|-----------|-------|
| `--primary` | Blue 600 | Blue 500 | Primary actions, links |
| `--primary-foreground` | White | White | Text on primary |
| `--secondary` | Gray 100 | Gray 800 | Secondary buttons |
| `--accent` | Gray 100 | Gray 800 | Highlighted areas |

#### Feedback Colors

| Token | Light Mode | Dark Mode | Usage |
|-------|------------|-----------|-------|
| `--destructive` | Red 600 | Red 500 | Errors, delete actions |
| `--success-*` | Green scale | Green scale | Success states |
| `--warning-*` | Amber scale | Amber scale | Warnings |
| `--error-*` | Red scale | Red scale | Error states |
| `--info-*` | Blue scale | Blue scale | Information |

#### Surface Colors

| Token | Usage |
|-------|-------|
| `--background` | Page background |
| `--foreground` | Primary text |
| `--card` | Card backgrounds |
| `--popover` | Dropdown/popover backgrounds |
| `--muted` | Muted backgrounds, disabled states |
| `--muted-foreground` | Secondary text, placeholders |

#### State Colors

```css
/* Interactive states */
--ring              /* Focus ring color */
--border            /* Default border */
--input             /* Input borders */

/* Status badges */
--success-100 to --success-900
--warning-100 to --warning-900
--error-100 to --error-900
--info-100 to --info-900
```

### Usage Examples

```tsx
// ✅ CORRECT - Semantic colors
<Button className="bg-primary text-primary-foreground" />
<Badge className="bg-success-100 text-success-700" />
<div className="text-muted-foreground" />

// ❌ WRONG - Raw Tailwind colors
<Button className="bg-blue-600 text-white" />
<Badge className="bg-green-100 text-green-700" />
```

### Badge Variants

```tsx
// Use semantic variants
<Badge variant="default">Default</Badge>
<Badge variant="secondary">Secondary</Badge>
<Badge variant="destructive">Error</Badge>
<Badge variant="outline">Outline</Badge>
<Badge variant="success">Success</Badge>
<Badge variant="warning">Warning</Badge>
<Badge variant="info">Info</Badge>
```

---

## Typography

### Font Families

| Token | Font Stack | Usage |
|-------|------------|-------|
| `--font-sans` | Inter, system-ui | Body text, UI elements |
| `--font-display` | Plus Jakarta Sans | Headings, titles |
| `--font-mono` | JetBrains Mono | Code, data |

### Font Sizes (Dense UI Scale)

| Token | Size | Pixels | Usage |
|-------|------|--------|-------|
| `--text-2xs` | 0.625rem | 10px | Tiny labels |
| `--text-xs` | 0.6875rem | 11px | Small labels |
| `--text-sm` | 0.75rem | 12px | Secondary text |
| `--text-base` | 0.8125rem | 13px | **Body text (DEFAULT)** |
| `--text-md` | 0.875rem | 14px | Emphasized body |
| `--text-lg` | 1rem | 16px | Subheadings |
| `--text-xl` | 1.125rem | 18px | Section titles |
| `--text-2xl` | 1.25rem | 20px | Page titles |
| `--text-3xl` | 1.5rem | 24px | Major headings |

### Font Weights

| Token | Weight | Usage |
|-------|--------|-------|
| `--font-normal` | 400 | Body text |
| `--font-medium` | 500 | Emphasized text, labels |
| `--font-semibold` | 600 | Subheadings |
| `--font-bold` | 700 | Headings |

### Heading Styles

```tsx
// Page title - Plus Jakarta Sans
<h1 className="text-2xl md:text-3xl font-bold font-display tracking-tight">
  Page Title
</h1>

// Section title
<h2 className="text-xl font-semibold font-display">
  Section Title
</h2>

// Card title
<h3 className="text-lg font-medium">
  Card Title
</h3>
```

---

## Spacing & Layout

### Spacing Scale (4px base unit)

| Token | Value | Pixels | Usage |
|-------|-------|--------|-------|
| `--spacing-0` | 0 | 0px | Reset |
| `--spacing-px` | 1px | 1px | Borders |
| `--spacing-0-5` | 0.125rem | 2px | Micro spacing |
| `--spacing-xs` | 0.25rem | 4px | Tight gaps |
| `--spacing-sm` | 0.5rem | 8px | Small gaps |
| `--spacing-md` | 0.75rem | 12px | Medium gaps |
| `--spacing-lg` | 1rem | 16px | Standard gaps |
| `--spacing-xl` | 1.5rem | 24px | Section gaps |
| `--spacing-2xl` | 2rem | 32px | Large sections |
| `--spacing-3xl` | 2.5rem | 40px | Page sections |
| `--spacing-4xl` | 3rem | 48px | Major sections |

### Layout Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--sidebar-width` | 256px | Expanded sidebar |
| `--sidebar-width-collapsed` | 72px | Collapsed sidebar |
| `--header-height` | 56px | Top header |
| `--content-max-width` | 1600px | Main content area |
| `--page-padding-x` | 1rem | Horizontal page padding |
| `--page-padding-y` | 1.5rem | Vertical page padding |
| `--section-gap` | 1.5rem | Gap between sections |
| `--content-gap` | 1rem | Gap between content items |

### Border Radius

| Token | Value | Pixels | Usage |
|-------|-------|--------|-------|
| `--radius-none` | 0 | 0px | Sharp corners |
| `--radius-sm` | 0.25rem | 4px | Buttons, inputs |
| `--radius-md` | 0.375rem | 6px | Cards, dialogs |
| `--radius-lg` | 0.5rem | 8px | Large cards |
| `--radius-xl` | 0.75rem | 12px | Modals |
| `--radius-2xl` | 1rem | 16px | Special cases |
| `--radius-full` | 9999px | - | Pills, avatars |

---

## Component Specifications

### Button

| Size | Height | Padding | Font Size |
|------|--------|---------|-----------|
| `sm` | 28px | px-2.5 | 12px |
| `default` | 32px | px-3 | 13px |
| `lg` | 40px | px-4 | 14px |
| `icon` | 32px | - | - |

```tsx
// Variants
<Button variant="default">Primary Action</Button>
<Button variant="secondary">Secondary</Button>
<Button variant="destructive">Delete</Button>
<Button variant="outline">Outline</Button>
<Button variant="ghost">Ghost</Button>
<Button variant="link">Link</Button>

// Sizes
<Button size="sm">Small</Button>
<Button size="default">Default</Button>
<Button size="lg">Large</Button>
<Button size="icon"><Icon /></Button>
```

### Input

| Size | Height | Padding | Font Size |
|------|--------|---------|-----------|
| `sm` | 28px | px-2 py-1 | 12px |
| `default` | 32px | px-2.5 py-1.5 | 13px |
| `lg` | 40px | px-3 py-2 | 14px |

```tsx
<Input placeholder="Enter text..." />
<Input className="h-7" /> {/* Small */}
<Input className="h-10" /> {/* Large */}
```

### Select

Same height specifications as Input. Uses Radix UI primitives.

```tsx
<Select>
  <SelectTrigger className="w-[180px]">
    <SelectValue placeholder="Select..." />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="option1">Option 1</SelectItem>
    <SelectItem value="option2">Option 2</SelectItem>
  </SelectContent>
</Select>
```

### Badge

| Variant | Background | Text | Border |
|---------|------------|------|--------|
| `default` | primary | primary-foreground | - |
| `secondary` | secondary | secondary-foreground | - |
| `destructive` | destructive | destructive-foreground | - |
| `outline` | transparent | foreground | border |
| `success` | success-100 | success-700 | - |
| `warning` | warning-100 | warning-700 | - |
| `info` | info-100 | info-700 | - |

### Card

```tsx
<Card>
  <CardHeader>
    <CardTitle>Title</CardTitle>
    <CardDescription>Description text</CardDescription>
  </CardHeader>
  <CardContent>
    {/* Content */}
  </CardContent>
  <CardFooter>
    {/* Actions */}
  </CardFooter>
</Card>
```

### Table

| Property | Value |
|----------|-------|
| Row Height (dense) | 40px (`--table-row-height`) |
| Row Height (compact) | 32px (`--table-row-height-compact`) |
| Header Background | `muted/50` |
| Border | `border` token |

---

## Layout Components

### PageContainer

Standardized wrapper for page content with consistent padding and max-width.

```tsx
import { PageContainer } from "@/components/layouts/PageContainer";

// Full width (default) - for dashboards, wide tables
<PageContainer maxWidth="full">
  {children}
</PageContainer>

// Extra large - for admin tables
<PageContainer maxWidth="xl">
  {children}
</PageContainer>

// Large - for standard pages
<PageContainer maxWidth="lg">
  {children}
</PageContainer>

// Medium - for content pages
<PageContainer maxWidth="md">
  {children}
</PageContainer>

// Small - for forms, settings
<PageContainer maxWidth="sm">
  {children}
</PageContainer>
```

| maxWidth | CSS Class | Pixels |
|----------|-----------|--------|
| `sm` | max-w-2xl | 672px |
| `md` | max-w-4xl | 896px |
| `lg` | max-w-6xl | 1152px |
| `xl` | max-w-7xl | 1280px |
| `full` | (none) | 1600px (from Main) |

### PageHeader

Standardized page header with title, description, icon, back button, and actions.

```tsx
import { PageHeader } from "@/components/layouts/PageHeader";

// Standard header
<PageHeader
  title="Page Title"
  description="Description of this page"
/>

// With icon
<PageHeader
  title="Settings"
  icon={<Settings className="h-8 w-8 text-primary" />}
  description="Manage your settings"
/>

// With back button
<PageHeader
  title="Lead Details"
  backButton={{ href: "/leads", label: "Back to Leads" }}
/>

// With actions
<PageHeader
  title="Users"
  description="Manage system users"
  actions={
    <>
      <Button variant="outline">Export</Button>
      <Button><Plus className="mr-2 h-4 w-4" />Add User</Button>
    </>
  }
/>
```

### DashboardLayout

Main layout wrapper with sidebar, header, and content area.

```
┌──────────────────────────────────────────────────────┐
│ SecurityBanner (conditional)                          │
├────────┬─────────────────────────────────────────────┤
│        │ Header (56px)                               │
│ Side   ├─────────────────────────────────────────────┤
│ bar    │                                             │
│ (256px │ Main Content                                │
│  or    │ ├─ Breadcrumbs                              │
│  72px) │ └─ Page Content (max-width: 1600px)         │
│        │                                             │
├────────┴─────────────────────────────────────────────┤
│ MobileBottomNav (mobile only)                        │
└──────────────────────────────────────────────────────┘
```

---

## Icons

### Icon Library

Using **Lucide React** for all icons.

```tsx
import { Search, Plus, Trash2, Settings } from "lucide-react";
```

### Icon Sizes

| Token | Size | Usage |
|-------|------|-------|
| `--icon-xs` | 12px | Inline with small text |
| `--icon-sm` | 14px | Inline with body text |
| `--icon-md` | 16px | **Default** - buttons, inputs |
| `--icon-lg` | 20px | Emphasized icons |
| `--icon-xl` | 24px | Headers, empty states |

### Icon Usage

```tsx
// In buttons
<Button>
  <Plus className="mr-2 h-4 w-4" />
  Add Item
</Button>

// In inputs
<div className="relative">
  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
  <Input className="pl-9" />
</div>

// In page headers
<PageHeader
  title="Dashboard"
  icon={<LayoutDashboard className="h-6 w-6 text-primary" />}
/>
```

---

## Animation & Motion

### Duration Tokens

| Token | Duration | Usage |
|-------|----------|-------|
| `--duration-instant` | 50ms | Micro-interactions (checkboxes) |
| `--duration-fast` | 100ms | Button clicks, hovers |
| `--duration-normal` | 150ms | Modals, dropdowns |
| `--duration-slow` | 200ms | Page transitions |
| `--duration-slower` | 300ms | Complex animations |

### Easing Functions

| Token | Curve | Usage |
|-------|-------|-------|
| `--ease-default` | cubic-bezier(0.4, 0, 0.2, 1) | General purpose |
| `--ease-in` | cubic-bezier(0.4, 0, 1, 1) | Exit animations |
| `--ease-out` | cubic-bezier(0, 0, 0.2, 1) | Enter animations |
| `--ease-in-out` | cubic-bezier(0.4, 0, 0.2, 1) | Symmetric animations |
| `--ease-bounce` | cubic-bezier(0.68, -0.55, 0.265, 1.55) | Playful feedback |

### Common Animations

```tsx
// Fade in
<div className="animate-fade-in" />

// Transition on hover
<div className="transition-all duration-150 ease-out hover:shadow-md" />

// Sidebar transition
<aside className="transition-all duration-300 ease-in-out" />
```

---

## Patterns & Best Practices

### Page Structure Pattern

```tsx
export default function MyPage() {
  return (
    <PageContainer maxWidth="xl">
      <PageHeader
        title="My Page"
        description="Description of this page"
        actions={<Button>Action</Button>}
      />

      {/* Filters Card */}
      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Filter controls */}
        </CardContent>
      </Card>

      {/* Main Content Card */}
      <Card>
        <CardContent className="p-0">
          <Table>{/* ... */}</Table>
        </CardContent>
      </Card>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        {/* ... */}
      </div>
    </PageContainer>
  );
}
```

### Form Pattern

```tsx
<PageContainer maxWidth="sm">
  <PageHeader
    title="Create Item"
    backButton={{ href: "/items" }}
  />

  <Card>
    <CardHeader>
      <CardTitle>Item Details</CardTitle>
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input id="name" />
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">Description</Label>
        <Textarea id="description" />
      </div>
    </CardContent>
    <CardFooter className="flex justify-end gap-2">
      <Button variant="outline">Cancel</Button>
      <Button>Save</Button>
    </CardFooter>
  </Card>
</PageContainer>
```

### Status Badge Pattern

```tsx
const STATUS_CONFIG = {
  active: { label: "Active", variant: "success" },
  pending: { label: "Pending", variant: "warning" },
  inactive: { label: "Inactive", variant: "secondary" },
  error: { label: "Error", variant: "destructive" },
} as const;

// Usage
<Badge variant={STATUS_CONFIG[status]?.variant ?? "secondary"}>
  {STATUS_CONFIG[status]?.label ?? status}
</Badge>
```

### Loading State Pattern

```tsx
// Skeleton loading
{isLoading ? (
  <div className="space-y-2">
    {Array.from({ length: 5 }).map((_, i) => (
      <Skeleton key={i} className="h-12 w-full" />
    ))}
  </div>
) : (
  <Table>{/* ... */}</Table>
)}
```

### Empty State Pattern

```tsx
<Card>
  <CardContent className="py-12">
    <div className="text-center text-muted-foreground">
      <FileQuestion className="h-16 w-16 mx-auto mb-4 opacity-20" />
      <p className="font-medium">No items found</p>
      <p className="text-sm mt-2">Create your first item to get started</p>
      <Button className="mt-4">
        <Plus className="mr-2 h-4 w-4" />
        Create Item
      </Button>
    </div>
  </CardContent>
</Card>
```

---

## Anti-Patterns (NEVER DO)

### Color Anti-Patterns

```tsx
// ❌ WRONG - Raw Tailwind colors
<div className="bg-blue-500 text-white" />
<div className="text-gray-500" />
<Badge className="bg-green-100 text-green-800" />

// ✅ CORRECT - Semantic tokens
<div className="bg-primary text-primary-foreground" />
<div className="text-muted-foreground" />
<Badge variant="success" />
```

### Spacing Anti-Patterns

```tsx
// ❌ WRONG - Arbitrary values
<div className="p-[17px] mt-[23px]" />

// ✅ CORRECT - Token-based spacing
<div className="p-4 mt-6" />
```

### Typography Anti-Patterns

```tsx
// ❌ WRONG - Inconsistent heading styles
<h1 className="text-2xl font-bold">Title</h1>

// ✅ CORRECT - Include font-display for headings
<h1 className="text-2xl font-bold font-display tracking-tight">Title</h1>
```

### Layout Anti-Patterns

```tsx
// ❌ WRONG - Hardcoded values
<div className="max-w-[1600px] py-6" />

// ✅ CORRECT - CSS variables via components
<PageContainer maxWidth="full">
  {/* Uses --content-max-width, --page-padding-y */}
</PageContainer>
```

---

## Z-Index Scale

| Token | Value | Usage |
|-------|-------|-------|
| `--z-dropdown` | 50 | Dropdowns, selects |
| `--z-sticky` | 100 | Sticky headers |
| `--z-fixed` | 200 | Fixed elements |
| `--z-modal-backdrop` | 300 | Modal overlays |
| `--z-modal` | 400 | Modal content |
| `--z-popover` | 500 | Popovers, tooltips |
| `--z-tooltip` | 600 | Tooltips |
| `--z-toast` | 700 | Toast notifications |

---

## Shadow System

| Token | Usage |
|-------|-------|
| `--shadow-xs` | Subtle lift |
| `--shadow-sm` | Cards, buttons |
| `--shadow-md` | Dropdowns |
| `--shadow-lg` | Modals |
| `--shadow-xl` | Popovers |
| `--shadow-primary` | Primary button hover |
| `--shadow-success` | Success state emphasis |
| `--shadow-error` | Error state emphasis |

---

## Quick Reference

### Common Class Combinations

```tsx
// Page title
"text-2xl md:text-3xl font-bold font-display tracking-tight"

// Section title
"text-xl font-semibold font-display"

// Card title
"text-lg font-medium"

// Body text
"text-sm text-muted-foreground"

// Small label
"text-xs text-muted-foreground"

// Input with icon
"pl-9" // with icon positioned at left-3

// Dense table row
"h-10" // 40px

// Standard gap between items
"space-y-4" or "gap-4"

// Section gap
"space-y-6" or "gap-6"
```

### Import Paths

```tsx
// Layout components
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";

// UI components
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Icons
import { Plus, Search, Trash2 } from "lucide-react";

// Utilities
import { cn } from "@/lib/utils";
```

---

## Changelog

### v3.0 (2026-01-28)
- Added layout CSS variables for sidebar, header, content
- Migrated pages to use PageContainer component
- Standardized semantic color usage across all components
- Added Badge variants for success, warning, info states
- Updated spacing to use CSS variables

### v2.0 (2026-01-27)
- Introduced semantic color system
- Added Plus Jakarta Sans for display typography
- Reduced base font size to 13px for dense UI
- Added foundation.css with all design tokens

### v1.0 (Initial)
- Basic Tailwind + shadcn/ui setup
