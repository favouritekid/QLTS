# UI RULEBOOK - QLTS Frontend

> Tài liệu hướng dẫn UI cho dev team QLTS.
> Đọc trước khi code bất kỳ component nào.

---

## 1. Nguyên tắc cốt lõi

### 1.1 Thin Client Philosophy

```
❌ KHÔNG tính toán business logic ở frontend
✅ Hiển thị ĐÚNG những gì backend trả về
```

| Sai | Đúng |
|-----|------|
| `isEligible = gpa >= 7.0` | `isEligible = profile.eligibility_status === "eligible"` |
| `user.role === "admin"` | `profile.can_approve` |
| `status === "submitted" && !approved_at` | `status === "submitted"` |

### 1.2 Status-Driven UI

Backend owns status values. Frontend owns presentation only.

```tsx
// ✅ Đúng - Dùng config
import { AdmissionBadge } from "@/components/common/status"
<AdmissionBadge status={profile.status} />

// ❌ Sai - Hardcode màu
<Badge className="bg-green-100 text-green-800">Đã duyệt</Badge>
```

---

## 2. Semantic Tokens

### 2.1 Khi nào dùng Semantic Tokens?

| Trường hợp | Dùng |
|------------|------|
| Badge hiển thị admission status | `bg-admission-approved-bg` |
| Badge hiển thị lead status | `bg-lead-qualified-bg` |
| Score indicator | `bg-score-excellent-bg` |
| General UI (button, card) | `bg-primary`, `bg-muted` |

### 2.2 Token Reference

```css
/* Admission Status */
bg-admission-draft-bg      text-admission-draft-fg
bg-admission-submitted-bg  text-admission-submitted-fg
bg-admission-reviewing-bg  text-admission-reviewing-fg
bg-admission-approved-bg   text-admission-approved-fg
bg-admission-rejected-bg   text-admission-rejected-fg
bg-admission-enrolled-bg   text-admission-enrolled-fg

/* Lead Pipeline */
bg-lead-new-bg        text-lead-new-fg
bg-lead-contacted-bg  text-lead-contacted-fg
bg-lead-qualified-bg  text-lead-qualified-fg
bg-lead-converted-bg  text-lead-converted-fg
bg-lead-lost-bg       text-lead-lost-fg

/* Score Level */
bg-score-excellent-bg  text-score-excellent-fg
bg-score-good-bg       text-score-good-fg
bg-score-average-bg    text-score-average-fg
bg-score-poor-bg       text-score-poor-fg
```

---

## 3. Components

### 3.1 Status Badges

```tsx
import {
  AdmissionBadge,
  LeadBadge,
  ScoreLevelBadge,
  StatusBadge,
} from "@/components/common/status"

// Admission status (recommended)
<AdmissionBadge status="approved" />
<AdmissionBadge status="rejected" compact />

// Lead status
<LeadBadge status="qualified" />
<LeadBadge status="converted" showDot />

// Score level
<ScoreLevelBadge level="excellent" />

// Generic (legacy support)
<StatusBadge variant="success">Hoàn thành</StatusBadge>
```

### 3.2 Admission Stepper

```tsx
import { AdmissionStepper, MiniStepper } from "@/components/admission"

// Full stepper
<AdmissionStepper currentStatus="submitted" />

// Compact for sidebar
<AdmissionStepper currentStatus="approved" compact />

// Vertical layout
<AdmissionStepper currentStatus="reviewing" vertical />

// Mini dots for cards
<MiniStepper currentStatus="enrolled" />
```

---

## 4. Patterns

### 4.1 Hiển thị Status trong Card

```tsx
function AdmissionCard({ admission }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{admission.applicant_name}</CardTitle>
          <AdmissionBadge status={admission.status} />
        </div>
      </CardHeader>
      <CardContent>
        <MiniStepper currentStatus={admission.status} />
      </CardContent>
    </Card>
  )
}
```

### 4.2 Hiển thị Status trong Table

```tsx
const columns = [
  {
    accessorKey: "status",
    header: "Trạng thái",
    cell: ({ row }) => (
      <AdmissionBadge status={row.original.status} compact />
    ),
  },
]
```

### 4.3 Conditional Actions

```tsx
// ✅ Đúng - Dùng permission flags từ backend
{profile.can_submit && <SubmitButton />}
{profile.can_approve && <ApproveButton />}
{profile.can_edit && <EditButton />}

// ❌ Sai - Check role string
{user.role === "admin" && <ApproveButton />}
```

---

## 5. File Structure

```
src/
├── components/
│   ├── admission/          # Admission-specific components
│   │   ├── AdmissionStepper.tsx
│   │   └── index.ts
│   ├── common/
│   │   └── status/         # Status display components
│   │       ├── StatusBadge.tsx
│   │       └── index.ts
│   └── ui/                 # shadcn/ui base components
│
├── lib/
│   ├── ui-config/          # UI configuration
│   │   └── status-badge.config.ts
│   └── status-config.ts    # Legacy status config (deprecated)
│
└── styles/
    ├── globals.css         # Main entry
    ├── tokens/
    │   ├── foundation.css  # Base tokens
    │   ├── semantic.css    # Semantic aliases
    │   ├── admission.css   # QLTS-specific tokens
    │   └── components.css  # Utilities
    └── themes/
        ├── light.css
        └── dark.css
```

---

## 6. Migration Guide

### Từ hardcoded colors → Semantic tokens

```tsx
// Trước
<Badge className="bg-green-100 text-green-800">Đã duyệt</Badge>

// Sau
<AdmissionBadge status="approved" />
// hoặc
<Badge className="bg-admission-approved-bg text-admission-approved-fg">
  Đã duyệt
</Badge>
```

### Từ StatusFromMap → Semantic Badges

```tsx
// Trước
<StatusFromMap status={lead.status} statusMap={LEAD_STATUS_MAP} />

// Sau
<LeadBadge status={lead.status} />
```

---

## 7. Checklist

Trước khi submit PR, kiểm tra:

- [ ] Status được hiển thị bằng semantic badge (không hardcode màu)
- [ ] Actions được control bằng permission flags (không check role)
- [ ] Không tính toán business logic ở frontend
- [ ] Dark mode hoạt động đúng
- [ ] Component có tooltip/description cho UX

---

## 8. Quick Reference

### Import paths

```tsx
// Status badges
import { AdmissionBadge, LeadBadge } from "@/components/common/status"

// Stepper
import { AdmissionStepper, MiniStepper } from "@/components/admission"

// Config (khi cần customize)
import { getStatusBadgeConfig } from "@/lib/ui-config/status-badge.config"
```

### Colors by status

| Status | Background | Foreground |
|--------|------------|------------|
| Draft | Xám nhạt | Xám đậm |
| Submitted | Xanh dương nhạt | Xanh dương đậm |
| Reviewing | Vàng nhạt | Vàng đậm |
| Approved | Xanh lá nhạt | Xanh lá đậm |
| Rejected | Đỏ nhạt | Đỏ đậm |
| Enrolled | Tím nhạt | Tím đậm |

---

*Last updated: 2026-01-26*
