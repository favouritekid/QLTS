# BaseCard System Standards

## Overview

Hệ thống BaseCard cung cấp layout đồng nhất cho tất cả mobile data cards trong ứng dụng.

**Nguyên tắc cốt lõi:** *"Card khác dữ liệu, không khác cấu trúc"*

---

## Quy tắc BẮT BUỘC

### 1. Cấu trúc Layout

Mọi mobile data card PHẢI tuân theo cấu trúc:

```
┌─────────────────────────────────────────┐
│ [☑] CardHeader          [CardActions ⋮] │
│     CardBody                            │
│     CardMeta                            │
└─────────────────────────────────────────┘
```

**Thứ tự components:**
1. `CardHeader` - Luôn đầu tiên
2. `CardBody` - Chứa business fields
3. `CardMeta` - Status/time/tags cuối cùng
4. `CardActions` - Tự động positioned top-right

### 2. Spacing & Padding

| Token | Giá trị | Sử dụng |
|-------|---------|---------|
| Card padding | `p-4` (16px) | Tất cả cards |
| Gap checkbox-content | `gap-3` (12px) | BaseCard internal |
| Gap giữa sections | `space-y-2` (8px) | Giữa Header/Body/Meta |
| Gap giữa fields | `space-y-1` (4px) | Trong CardBody |
| Gap meta items | `gap-2` (8px) | Trong CardMeta |

**❌ KHÔNG được dùng:**
- `p-3` (quá nhỏ)
- `p-6` (quá lớn, dành cho dashboard cards)
- Custom padding values

### 3. Typography

| Element | Class | Kích thước |
|---------|-------|------------|
| Title | `font-medium text-sm` | 14px, medium weight |
| Subtitle | `text-xs text-muted-foreground` | 12px, muted |
| Field label | `text-xs text-muted-foreground` | 12px, muted |
| Field value | `text-sm` | 14px |
| Meta text | `text-xs text-muted-foreground` | 12px, muted |

**❌ KHÔNG được dùng:**
- `font-semibold` cho title (quá nặng)
- `text-[10px]` (quá nhỏ, khó đọc)
- Custom font sizes

### 4. Action Menu Position

**Quy tắc:**
- VỊ TRÍ: Top-right corner, cố định
- ICON: `MoreVertical` (⋮) - KHÔNG dùng `MoreHorizontal`
- SIZE: `h-8 w-8` button với `h-4 w-4` icon

```tsx
// ✅ CHUẨN
<CardActions>
  <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button variant="ghost" size="icon" className="h-8 w-8">
        <MoreVertical className="h-4 w-4" />
      </Button>
    </DropdownMenuTrigger>
    ...
  </DropdownMenu>
</CardActions>

// ❌ SAI
<CardActions>
  <Button>View</Button>  {/* Không dùng text button */}
  <Eye className="h-4 w-4" /> {/* Không dùng icon trực tiếp */}
</CardActions>
```

### 5. Badge & Status

**Quy tắc:**
- SIZE: Sử dụng default Badge size (text-xs tự động)
- VỊ TRÍ: Trong CardMeta hoặc bên cạnh title trong CardHeader
- VARIANT: Sử dụng semantic variants (`success`, `destructive`, `warning`, `secondary`)

```tsx
// ✅ CHUẨN
<CardHeader
  title="Nguyễn Văn A"
  badge={<Badge variant="success">Hot</Badge>}
/>

// ❌ SAI
<CardHeader
  title="Nguyễn Văn A"
  badge={<span className="text-[10px] px-1 bg-green-500">Hot</span>}
/>
```

### 6. Time/Date Format

**Format chuẩn hóa:**

| Context | Format | Example |
|---------|--------|---------|
| Recent activity | `relative` | "2 giờ trước" |
| Historical data | `date` | "15/01/2025" |
| Schedules | `datetime` | "15/01 14:30" |
| Same-day events | `time` | "14:30" |

```tsx
// ✅ CHUẨN - sử dụng CardTime
<CardMeta>
  <CardTime date={createdAt} format="relative" />
</CardMeta>

// ❌ SAI - format tự custom
<CardMeta>
  <span>{format(date, "yyyy-MM-dd")}</span>
</CardMeta>
```

### 7. Checkbox/Selection

**Quy tắc:**
- VỊ TRÍ: Top-left, trong BaseCard wrapper
- CONTROL: `showCheckbox` prop để toggle visibility
- STATE: `selected` và `onSelect` props

```tsx
// ✅ CHUẨN
<BaseCard
  selected={isSelected}
  onSelect={(checked) => handleSelect(id, checked)}
  showCheckbox={selectionMode}
>
  ...
</BaseCard>
```

---

## Cards PHẢI sử dụng BaseCard

### Nhóm A: Mobile Data Cards (BẮT BUỘC)

| Card | File | Trạng thái |
|------|------|------------|
| MobileLeadCard | `components/leads/command-center/` | ⚠️ Cần refactor |
| AdmissionCard | `admissions/_components/` | ⚠️ Cần refactor |
| UserCard | `admin/users/_components/` | ⚠️ Cần refactor |
| AuditLogCard | Chưa có | 🆕 Cần tạo |
| DeletedItemCard | Chưa có | 🆕 Cần tạo |
| NotificationCard | `notifications/_components/` | ⚠️ Cần refactor |

### Nhóm B: Dashboard Cards (KHÔNG áp dụng)

Các cards này có layout specialized, KHÔNG nên force vào BaseCard:
- `KPICard` - Metric display với số lớn
- `WorkloadCard` - Progress visualization
- `AnnualProgressCard` - Chart integration

### Nhóm C: Specialized Cards (KHÔNG áp dụng)

- `LeadKanbanCard` - Drag & drop context
- Health check cards - Domain-specific complex

---

## Import & Usage

```tsx
import {
  BaseCard,
  CardHeader,
  CardBody,
  CardField,
  CardFieldRow,
  CardMeta,
  CardTime,
  CardActions,
} from "@/components/ui/base-card"

function MyCard({ item, isSelected, onSelect }) {
  return (
    <BaseCard
      selected={isSelected}
      onSelect={onSelect}
      showCheckbox
    >
      <CardHeader
        title={item.name}
        subtitle={`ID: ${item.id}`}
        badge={<Badge>{item.status}</Badge>}
      />
      <CardBody>
        <CardField label="Email" value={item.email} />
        <CardField label="Phone" value={item.phone} />
      </CardBody>
      <CardMeta>
        <Badge variant="secondary">{item.type}</Badge>
        <CardTime date={item.createdAt} format="relative" />
      </CardMeta>
      <CardActions>
        <DropdownMenu>...</DropdownMenu>
      </CardActions>
    </BaseCard>
  )
}
```

---

## Checklist cho mỗi Card mới

- [ ] Sử dụng `BaseCard` wrapper
- [ ] `CardHeader` với title và optional subtitle/badge
- [ ] `CardBody` với 2-4 `CardField` components
- [ ] `CardMeta` với badges và `CardTime`
- [ ] `CardActions` với `DropdownMenu` + `MoreVertical`
- [ ] Padding là `p-4` (được BaseCard tự apply)
- [ ] Title là `font-medium text-sm`
- [ ] Không có custom font sizes (text-[10px], etc.)
- [ ] Time format sử dụng `CardTime` component
