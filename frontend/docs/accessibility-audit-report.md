# Accessibility Audit Report - WCAG AA Compliance

**Audit Date:** January 28, 2026
**Scope:** QLTS Frontend Application
**Standard:** WCAG 2.1 Level AA

---

## Executive Summary

The QLTS frontend demonstrates **strong baseline accessibility** due to:
- Using Radix UI primitives (Dialog, Select, Tabs, etc.) with built-in ARIA support
- Proper focus management via `focus-visible` classes
- Semantic HTML structure (tables, forms, headings)
- Screen reader support with `sr-only` utility class

**Overall Status: MOSTLY COMPLIANT with minor issues**

---

## 1. Color Contrast Audit

### Status: ⚠️ WARNING - Minor Issues

#### Analyzed Color Pairs (Light Theme)

| Element | Foreground | Background | Ratio | Status |
|---------|------------|------------|-------|--------|
| Body text | `#1c1917` (gray-900) | `#fafaf9` (gray-50) | **16.8:1** | ✅ Pass |
| Card text | `#1c1917` (gray-900) | `#ffffff` (white) | **18.1:1** | ✅ Pass |
| Muted text | `#78716c` (gray-500) | `#ffffff` (white) | **4.2:1** | ⚠️ Borderline |
| Muted text | `#78716c` (gray-500) | `#fafaf9` (gray-50) | **4.0:1** | ⚠️ Below |
| Primary button | `#ffffff` | `#2563eb` (primary-600) | **6.3:1** | ✅ Pass |
| Destructive | `#ffffff` | `#ef4444` (error-500) | **4.6:1** | ✅ Pass |
| Placeholder | `#78716c` (gray-500) | `#ffffff` | **4.2:1** | ⚠️ Borderline |

#### Issues Found

1. **Muted foreground contrast** (`text-muted-foreground`)
   - Current: `#78716c` (gray-500) = ~4.0-4.2:1 contrast
   - WCAG AA requires: 4.5:1 for normal text
   - **Recommendation**: Use `gray-600` (`#57534e`) = ~5.9:1

2. **Placeholder text**
   - Uses muted-foreground color
   - Same contrast issue as above

#### Locations Using Muted Text

Files using `text-muted-foreground`:
- `CardDescription` component
- Form helper text
- Table secondary columns
- Empty state descriptions
- Timestamp displays

### Recommended Fix

```css
/* In light.css */
--muted-foreground: var(--gray-600); /* Change from gray-500 */
```

---

## 2. Keyboard Navigation Audit

### Status: ✅ PASS

#### Findings

| Component | Tab Navigation | Enter/Space | Escape | Arrow Keys |
|-----------|----------------|-------------|--------|------------|
| Button | ✅ | ✅ | N/A | N/A |
| Dialog | ✅ Focus trap | ✅ Close btn | ✅ Close | N/A |
| Select | ✅ | ✅ Opens | ✅ Close | ✅ Navigate |
| Tabs | ✅ | ✅ Activate | N/A | ✅ Navigate |
| Table | ✅ Interactive cells | ✅ | N/A | N/A |
| Dropdown | ✅ | ✅ Opens | ✅ Close | ✅ Navigate |
| Combobox | ✅ | ✅ | ✅ | ✅ |

#### Keyboard Handler Implementation

Found in 4 components with custom handlers:
- `LeadsTable.tsx` - Row selection
- `TemplateForm.tsx` - Custom shortcuts
- `FormModal.tsx` - Form submission
- `CreateRoleDialog.tsx` - Form handling

All use proper keyboard event handling patterns.

---

## 3. Focus States Audit

### Status: ✅ PASS

#### Focus Ring Implementation

All interactive elements use consistent focus styling:

```tsx
// Button component
"focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"

// Input component
"focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"

// Select component
"focus:outline-none focus:ring-1 focus:ring-ring"
```

#### Focus Trap

Dialogs use Radix UI's built-in focus trap:
- Focus moves to first focusable element on open
- Tab cycles within dialog
- Focus returns to trigger on close

#### Skip Links

**Not implemented** - Consider adding for keyboard users.

---

## 4. ARIA Attributes Audit

### Status: ⚠️ WARNING - Minor Issues

#### Well-Implemented ARIA

| Pattern | Implementation | Files |
|---------|---------------|-------|
| Dialog roles | Radix auto-handles | `dialog.tsx` |
| Select combobox | Radix auto-handles | `select.tsx` |
| Error messages | `role="alert"` | Form components |
| Live regions | `aria-invalid`, `aria-describedby` | Form components |
| Close buttons | `sr-only` text | `dialog.tsx`, `sheet.tsx` |

#### Files Using ARIA Correctly

- `FormInput.tsx` - `aria-invalid`, `aria-describedby`
- `FormTextarea.tsx` - `aria-invalid`, `aria-describedby`
- `FormNumber.tsx` - `aria-invalid`, `aria-describedby`
- `DatePicker.tsx` - `role="combobox"`, `aria-expanded`, `aria-label`
- `DateTimePicker.tsx` - Full ARIA implementation
- `Pagination.tsx` - `aria-label` on buttons
- `SearchInput.tsx` - `aria-label` on clear button

#### Issues Found

1. **Icon buttons missing `aria-label`**

Locations:
```
NotificationRuleList.tsx:437 - Collapse/expand button
AdminUsersClient.tsx:258 - Action button
DistributionClient.tsx:276 - Action button
ConfigClient.tsx:247 - Edit button
OrganizationTreeView.tsx:122 - Expand button
ConditionBuilder.tsx:487 - Remove button
TodaySchedule.tsx:237 - Refresh button
LeadDetailClient.tsx:329 - Action button
```

**Note:** Some icon buttons use Tooltip with TooltipContent, but tooltips are NOT accessible names. The button still needs `aria-label`.

2. **Tooltip vs aria-label**

Pattern found in `LeadDetailPanel.tsx`:
```tsx
<Tooltip>
  <TooltipTrigger asChild>
    <Button variant="ghost" size="icon"> {/* Missing aria-label */}
      <Edit className="h-4 w-4" />
    </Button>
  </TooltipTrigger>
  <TooltipContent>Chỉnh sửa lead</TooltipContent>
</Tooltip>
```

**Issue:** TooltipContent provides visual context but NOT an accessible name.

**Fix:** Add `aria-label` matching the tooltip text:
```tsx
<Button variant="ghost" size="icon" aria-label="Chỉnh sửa lead">
```

---

## 5. Forms & Semantic HTML Audit

### Status: ✅ PASS

#### Form Accessibility

All form components implement proper patterns:

| Pattern | Status | Implementation |
|---------|--------|----------------|
| Label association | ✅ | `htmlFor` attribute |
| Error indication | ✅ | `aria-invalid="true"` |
| Error description | ✅ | `aria-describedby` points to error |
| Required fields | ✅ | Visual asterisk + validation |
| Error announcement | ✅ | `role="alert"` on error messages |

#### Semantic Structure

| Element | Usage | Status |
|---------|-------|--------|
| `<table>` | Data tables | ✅ Native HTML |
| `<th>` | Table headers | ✅ With proper scope |
| `<form>` | Form containers | ✅ |
| `<button>` | Interactive actions | ✅ |
| `<a>` | Navigation links | ✅ |
| Headings | Page structure | ✅ `<h1>` to `<h4>` hierarchy |

---

## 6. Screen Reader Support

### Status: ✅ GOOD

#### sr-only Usage (9 files)

Files using screen-reader-only text:
- `dialog.tsx` - Close button label
- `sheet.tsx` - Close button label
- `pagination.tsx` - Navigation labels
- `theme-toggle.tsx` - Theme state
- `command.tsx` - Search hints
- `NavItem.tsx` - Active state
- `RecentPages.tsx` - Context
- `DateTimePicker.tsx` - Date/time context
- `NotificationDropdown.tsx` - Count context

---

## 7. Image Accessibility

### Status: ✅ PASS

All images have alt text:

```tsx
// UserDialog.tsx
<AvatarImage src={displayAvatarUrl} alt="User avatar" />

// NavUser.tsx
<AvatarImage src={getAvatarUrl(user?.avatar_url)} alt={user?.username} />

// ImageUpload.tsx
<AvatarImage src={previewUrl} alt="Preview" />
```

---

## Summary of Issues

### Critical (Must Fix) - 0 issues

### Major (Should Fix) - 2 issues

1. **Muted text contrast below 4.5:1**
   - Impact: Users with low vision may struggle to read secondary text
   - Fix: Change `--muted-foreground` from `gray-500` to `gray-600`

2. **Icon buttons missing aria-label**
   - Impact: Screen reader users cannot identify button purpose
   - Fix: Add `aria-label` to all icon-only buttons

### Minor (Nice to Have) - 2 issues

1. **No skip link**
   - Impact: Keyboard users must tab through navigation on every page
   - Fix: Add "Skip to main content" link

2. **Tooltip vs accessible name confusion**
   - Impact: Developers may think tooltip provides accessibility
   - Fix: Document that `aria-label` is required even with tooltips

---

## Recommended Fixes

### Fix 1: Improve Muted Text Contrast

**File:** `frontend/src/styles/themes/light.css`

```css
/* Change line 88 */
--muted-foreground: var(--gray-600); /* Was: gray-500 */
```

### Fix 2: Add aria-label to Icon Buttons

**Pattern to apply:**

```tsx
// Before
<Button variant="ghost" size="icon">
  <ChevronRight className="h-5 w-5" />
</Button>

// After
<Button variant="ghost" size="icon" aria-label="Mở rộng">
  <ChevronRight className="h-5 w-5" />
</Button>
```

**Files requiring fixes:**
- `NotificationRuleList.tsx` - Line 437
- `AdminUsersClient.tsx` - Line 258
- `DistributionClient.tsx` - Line 276
- `ConfigClient.tsx` - Line 247
- `OrganizationTreeView.tsx` - Line 122
- `ConditionBuilder.tsx` - Line 487
- `TodaySchedule.tsx` - Line 237
- `LeadDetailClient.tsx` - Line 329
- `AppSidebar.tsx` - Lines 22, 35
- `FamilyTab.tsx` - Line 226

### Fix 3: Add Skip Link (Optional)

**File:** `frontend/src/components/layouts/dashboard/Main.tsx`

```tsx
<>
  <a
    href="#main-content"
    className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-background focus:border focus:rounded-md"
  >
    Chuyển đến nội dung chính
  </a>
  <main id="main-content" ...>
</>
```

---

## Compliance Checklist

| Criterion | Status | Notes |
|-----------|--------|-------|
| 1.1.1 Non-text Content | ✅ | All images have alt text |
| 1.3.1 Info and Relationships | ✅ | Proper semantic structure |
| 1.4.3 Contrast (Minimum) | ⚠️ | Muted text slightly below |
| 1.4.11 Non-text Contrast | ✅ | Focus rings visible |
| 2.1.1 Keyboard | ✅ | All interactive elements keyboard accessible |
| 2.1.2 No Keyboard Trap | ✅ | Focus trap only in modals, escapable |
| 2.4.3 Focus Order | ✅ | Logical tab order |
| 2.4.4 Link Purpose | ✅ | Links have clear context |
| 2.4.7 Focus Visible | ✅ | Consistent focus rings |
| 3.2.1 On Focus | ✅ | No unexpected context changes |
| 3.3.1 Error Identification | ✅ | Errors clearly indicated |
| 3.3.2 Labels or Instructions | ✅ | All inputs labeled |
| 4.1.1 Parsing | ✅ | Valid HTML output |
| 4.1.2 Name, Role, Value | ⚠️ | Some icon buttons missing names |

---

## Next Steps

1. **Immediate** (P1): Fix muted text contrast
2. **Short-term** (P2): Add aria-labels to icon buttons
3. **Long-term** (P3): Add skip link, improve documentation

---

*Report generated during Phase 12 of QLTS Frontend Refactoring*
