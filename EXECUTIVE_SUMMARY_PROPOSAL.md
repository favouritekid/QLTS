# 📋 Kế Hoạch Nâng Cấp Step 7: Executive Summary

## 🎯 Mục Tiêu

Biến Step 7 (Final Review) từ một màn hình đơn giản chỉ có nút "Nộp hồ sơ" thành một **trang tổng hợp điều hành** (Executive Summary) giúp Manager/Admin:
- Thẩm định nhanh toàn bộ hồ sơ trong một màn hình
- Không cần click qua lại giữa các tab
- Ra quyết định phê duyệt dựa trên thông tin đầy đủ

---

## 📊 Phân Tích Dữ Liệu Có Sẵn

### Backend Data (✅ Đã có - KHÔNG cần sửa backend)

```typescript
// AdmissionProfileResponse từ backend
{
  // 1. Thông tin định danh
  id: number,                    // Mã hồ sơ
  full_name: string,             // Họ tên
  citizen_id: string,            // CCCD
  lead_id: number,               // ID Lead

  // 2. Nguyện vọng (từ applied_rules)
  applied_rules: {
    admission_method: string,    // e.g., "HOC_BA", "THI_THPT"
    method_type: "gpa_only" | "subject_based" | "combined",
    academic_program: string,    // ⚠️ CẦN KIỂM TRA - có thể cần thêm vào backend
  },

  // 3. Trạng thái tổng quan
  eligibility_status: "eligible" | "ineligible" | "pending",
  completion_percent: number,    // 0-100
  status: "draft" | "submitted" | "approved" | "rejected" | "enrolled",

  // 4. Step Status (cho Health Check Grid)
  step_status: {
    1: "success" | "warning" | "error" | "locked",  // Personal Info
    2: "success" | "warning" | "error" | "locked",  // Family
    3: "success" | "warning" | "error" | "locked",  // Academic History
    4: "success" | "warning" | "error" | "locked",  // Scores
    5: "success" | "warning" | "error" | "locked",  // Documents
    6: "success" | "warning" | "error" | "locked",  // Tuition
    7: "success" | "warning" | "error" | "locked",  // Finalize
  },

  // 5. Điểm xét tuyển (cho Best N Snapshot)
  admission_scores: {
    gpa: number,                 // GPA (nếu là học bạ)
    selected_group: string,      // e.g., "A00", "D01"
    subject_scores: {            // Dynamic subjects
      math: number,
      physics: number,
      chemistry: number,
      // ...
    },
    total_score: number,
    average_score: number,
  },

  // 6. Tài liệu (cho Document Checklist)
  documents_checklist: [
    {
      code: string,
      label: string,
      is_mandatory: boolean,
      status: "missing" | "uploaded" | "verified" | "rejected" | "paper_submitted",
      file_path: string,
      uploaded_at: string,
      rejection_reason: string,
    }
  ],

  // 7. Validation Errors (cho warning badges)
  validation_errors: string[],
  grouped_validation_errors: {
    personal_info: { category: string, errors: string[], count: number },
    documents: { category: string, errors: string[], count: number },
    scores: { category: string, errors: string[], count: number },
  },

  // 8. Permissions (cho conditional rendering)
  permissions: {
    edit: boolean,
    approve: boolean,
    reject: boolean,
  }
}
```

---

## 🎨 Thiết Kế UI Components

### Layout Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ SECTION 1: HEADER - Thông Tin Định Danh & Trạng Thái           │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 2: HEALTH CHECK GRID - Lưới Kiểm Tra Nhanh             │
│   ┌──────────────┬──────────────┬──────────────┐               │
│   │ Hồ Sơ Pháp Lý│ Năng Lực H/T │ Thủ Tục & TC │               │
│   └──────────────┴──────────────┴──────────────┘               │
├─────────────────────────────────────────────────────────────────┤
│ SECTION 3: CHI TIẾT XÉT DUYỆT (Expandable)                     │
│   📊 Snapshot Điểm Chuẩn (Best N)                              │
│   📁 Checklist Tài Liệu                                         │
└─────────────────────────────────────────────────────────────────┘
```

### Section 1: Header - Thông Tin Định Danh & Trạng Thái

**Component**: `ExecutiveSummaryHeader`

```tsx
<Card className="border-2 border-primary/20">
  <CardHeader>
    <div className="flex justify-between items-start">
      {/* Left: Thông tin cơ bản */}
      <div>
        <CardTitle className="text-2xl">
          {profile.full_name}
        </CardTitle>
        <div className="space-y-1 text-sm text-muted-foreground mt-2">
          <div>Mã hồ sơ: <strong>#{profile.id}</strong></div>
          <div>CCCD: <strong>{profile.citizen_id}</strong></div>
          <div>Nguyện vọng: <strong>{getAdmissionMethodLabel(profile.applied_rules)}</strong></div>
        </div>
      </div>

      {/* Right: Status Badge */}
      <div>
        {profile.eligibility_status === "eligible" ? (
          <Badge className="text-lg px-6 py-3 bg-green-600">
            <CheckCircle2 className="mr-2" />
            Đủ Điều Kiện
          </Badge>
        ) : (
          <Badge variant="destructive" className="text-lg px-6 py-3">
            <AlertCircle className="mr-2" />
            Không Đủ Điều Kiện
          </Badge>
        )}
      </div>
    </div>

    {/* Progress Bar */}
    <div className="mt-4">
      <div className="flex justify-between text-sm mb-2">
        <span>Hoàn thành hồ sơ</span>
        <span className="font-semibold">{profile.completion_percent}%</span>
      </div>
      <Progress value={profile.completion_percent} className="h-3" />
    </div>
  </CardHeader>
</Card>
```

**Dữ liệu cần**:
- ✅ `profile.full_name`
- ✅ `profile.id`
- ✅ `profile.citizen_id`
- ⚠️ `profile.applied_rules.admission_method` (cần format label)
- ✅ `profile.eligibility_status`
- ✅ `profile.completion_percent`

---

### Section 2: Health Check Grid - Lưới Kiểm Tra Nhanh

**Component**: `HealthCheckGrid`

Chia thành **3 khối** tương ứng nhóm bước:

#### 2.1. Khối 1: Hồ Sơ Pháp Lý (Personal + Family)

```tsx
<Card>
  <CardHeader>
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <User className="w-5 h-5" />
        <CardTitle className="text-lg">Hồ Sơ Pháp Lý</CardTitle>
      </div>
      {/* Status Icon */}
      {isLegalDocsComplete() ? (
        <CheckCircle2 className="w-6 h-6 text-green-600" />
      ) : (
        <AlertTriangle className="w-6 h-6 text-amber-600" />
      )}
    </div>
  </CardHeader>
  <CardContent>
    {/* Step 1: Personal Info */}
    <HealthCheckItem
      label="Thông tin cá nhân"
      status={profile.step_status[1]}
      errorCount={getErrorCount(1)}
    />

    {/* Step 2: Family */}
    <HealthCheckItem
      label="Gia đình / Giám hộ"
      status={profile.step_status[2]}
      errorCount={getErrorCount(2)}
    />

    {/* Warnings cho optional fields */}
    {profile.step_status[1] === "warning" && (
      <Alert className="mt-2" variant="warning">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          Một số trường không bắt buộc chưa điền: Email, Nơi sinh, ...
        </AlertDescription>
      </Alert>
    )}
  </CardContent>
</Card>
```

**Logic**:
```typescript
function isLegalDocsComplete(): boolean {
  return profile.step_status[1] === "success" &&
         profile.step_status[2] === "success"
}

function getErrorCount(step: number): number {
  // Từ grouped_validation_errors
  if (step === 1) return profile.grouped_validation_errors?.personal_info?.count ?? 0
  // Step 2 không có validation errors riêng (backend không tạo)
  return 0
}
```

#### 2.2. Khối 2: Năng Lực Học Tập (Academic + Scores)

```tsx
<Card>
  <CardHeader>
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <GraduationCap className="w-5 h-5" />
        <CardTitle className="text-lg">Năng Lực Học Tập</CardTitle>
      </div>
      {isAcademicComplete() ? (
        <CheckCircle2 className="w-6 h-6 text-green-600" />
      ) : (
        <XCircle className="w-6 h-6 text-red-600" />
      )}
    </div>
  </CardHeader>
  <CardContent>
    {/* Hiển thị điểm TO */}
    <div className="bg-blue-50 rounded-lg p-4 mb-3">
      {profile.applied_rules.method_type === "gpa_only" ? (
        <div className="text-center">
          <div className="text-sm text-muted-foreground">GPA</div>
          <div className="text-3xl font-bold text-blue-600">
            {profile.admission_scores?.gpa ?? "N/A"}
          </div>
        </div>
      ) : (
        <div className="text-center">
          <div className="text-sm text-muted-foreground">
            Tổng điểm xét tuyển ({profile.admission_scores?.selected_group})
          </div>
          <div className="text-3xl font-bold text-blue-600">
            {profile.admission_scores?.total_score ?? "N/A"}
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            Trung bình: {profile.admission_scores?.average_score ?? "N/A"}
          </div>
        </div>
      )}
    </div>

    {/* Step 3: Academic History */}
    <HealthCheckItem
      label="Lịch sử học tập"
      status={profile.step_status[3]}
    />

    {/* Step 4: Scores */}
    <HealthCheckItem
      label="Điểm xét tuyển"
      status={profile.step_status[4]}
      errorCount={profile.grouped_validation_errors?.scores?.count ?? 0}
    />
  </CardContent>
</Card>
```

**Logic**:
```typescript
function isAcademicComplete(): boolean {
  return profile.step_status[3] === "success" &&
         profile.step_status[4] === "success"
}
```

#### 2.3. Khối 3: Thủ Tục & Tài Chính (Documents + Tuition)

```tsx
<Card>
  <CardHeader>
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <FileText className="w-5 h-5" />
        <CardTitle className="text-lg">Thủ Tục & Tài Chính</CardTitle>
      </div>
      {isAdminComplete() ? (
        <CheckCircle2 className="w-6 h-6 text-green-600" />
      ) : (
        <Clock className="w-6 h-6 text-amber-600" />
      )}
    </div>
  </CardHeader>
  <CardContent>
    {/* Tài liệu summary */}
    <div className="bg-amber-50 rounded-lg p-3 mb-3">
      <div className="flex justify-between text-sm">
        <span>Tài liệu đã nộp / Bắt buộc</span>
        <span className="font-semibold">
          {getVerifiedDocsCount()} / {getMandatoryDocsCount()}
        </span>
      </div>
      {getMissingDocsCount() > 0 && (
        <div className="text-xs text-red-600 mt-1">
          Còn thiếu: {getMissingDocsCount()} tài liệu
        </div>
      )}
    </div>

    {/* Step 5: Documents */}
    <HealthCheckItem
      label="Tài liệu pháp lý"
      status={profile.step_status[5]}
      errorCount={profile.grouped_validation_errors?.documents?.count ?? 0}
    />

    {/* Step 6: Tuition */}
    <HealthCheckItem
      label="Học phí"
      status={profile.step_status[6]}
    />
  </CardContent>
</Card>
```

**Logic**:
```typescript
function getVerifiedDocsCount(): number {
  return profile.documents_checklist.filter(
    doc => doc.is_mandatory && doc.status === "verified"
  ).length
}

function getMandatoryDocsCount(): number {
  return profile.documents_checklist.filter(doc => doc.is_mandatory).length
}

function getMissingDocsCount(): number {
  return profile.documents_checklist.filter(
    doc => doc.is_mandatory && doc.status === "missing"
  ).length
}

function isAdminComplete(): boolean {
  return profile.step_status[5] === "success" &&
         profile.step_status[6] === "success"
}
```

---

### Section 3: Chi Tiết Xét Duyệt (Expandable)

**Component**: `ReviewDetails`

#### 3.1. Snapshot Điểm Chuẩn (Best N)

```tsx
<Collapsible>
  <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 rounded-lg">
    <div className="flex items-center gap-2">
      <Calculator className="w-5 h-5" />
      <span className="font-semibold">Snapshot Điểm Chuẩn (Best N)</span>
    </div>
    <ChevronDown className="w-4 h-4" />
  </CollapsibleTrigger>

  <CollapsibleContent className="p-4">
    {profile.applied_rules.method_type === "gpa_only" ? (
      <div className="text-center text-muted-foreground">
        Phương thức này chỉ xét học bạ (GPA), không tính điểm từng môn
      </div>
    ) : (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Môn</TableHead>
            <TableHead className="text-right">Điểm</TableHead>
            <TableHead className="text-right">Trạng thái</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {Object.entries(profile.admission_scores?.subject_scores ?? {}).map(([subject, score]) => (
            <TableRow key={subject}>
              <TableCell className="font-medium">
                {getSubjectLabel(subject)}
              </TableCell>
              <TableCell className="text-right text-lg font-semibold">
                {score ?? "N/A"}
              </TableCell>
              <TableCell className="text-right">
                {isSubjectPassing(score) ? (
                  <Badge variant="success">Đạt</Badge>
                ) : (
                  <Badge variant="destructive">Liệt</Badge>
                )}
              </TableCell>
            </TableRow>
          ))}

          {/* Total Row */}
          <TableRow className="bg-blue-50 font-bold">
            <TableCell>Tổng điểm</TableCell>
            <TableCell className="text-right text-xl">
              {profile.admission_scores?.total_score ?? "N/A"}
            </TableCell>
            <TableCell className="text-right">
              {isTotalScorePassing() ? (
                <Badge variant="success">Đạt chuẩn</Badge>
              ) : (
                <Badge variant="destructive">Chưa đạt</Badge>
              )}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    )}
  </CollapsibleContent>
</Collapsible>
```

**Logic**:
```typescript
function getSubjectLabel(code: string): string {
  const labels: Record<string, string> = {
    math: "Toán",
    physics: "Vật lý",
    chemistry: "Hóa học",
    biology: "Sinh học",
    literature: "Ngữ văn",
    english: "Tiếng Anh",
    history: "Lịch sử",
    geography: "Địa lý",
  }
  return labels[code] ?? code
}

function isSubjectPassing(score: number | null): boolean {
  if (!score) return false
  const minScore = profile.applied_rules?.min_subject_score ?? 0
  return score >= minScore
}

function isTotalScorePassing(): boolean {
  const total = profile.admission_scores?.total_score ?? 0
  const minScore = profile.applied_rules?.min_score ?? 0
  return total >= minScore
}
```

#### 3.2. Checklist Tài Liệu

```tsx
<Collapsible>
  <CollapsibleTrigger className="flex items-center justify-between w-full p-4 hover:bg-muted/50 rounded-lg">
    <div className="flex items-center gap-2">
      <FileText className="w-5 h-5" />
      <span className="font-semibold">Checklist Tài Liệu Bắt Buộc</span>
    </div>
    <ChevronDown className="w-4 h-4" />
  </CollapsibleTrigger>

  <CollapsibleContent className="p-4">
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Tài liệu</TableHead>
          <TableHead className="text-center">Trạng thái</TableHead>
          <TableHead className="text-center">Loại bản</TableHead>
          <TableHead className="text-right">Ngày nộp</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {profile.documents_checklist
          .filter(doc => doc.is_mandatory)
          .map(doc => (
            <TableRow key={doc.code}>
              <TableCell className="font-medium">{doc.label}</TableCell>
              <TableCell className="text-center">
                {getDocumentStatusBadge(doc.status)}
              </TableCell>
              <TableCell className="text-center">
                {doc.submission_format ? (
                  <Badge variant="outline">
                    {getFormatLabel(doc.submission_format)}
                  </Badge>
                ) : (
                  <span className="text-muted-foreground">N/A</span>
                )}
              </TableCell>
              <TableCell className="text-right text-sm text-muted-foreground">
                {doc.uploaded_at ? formatDate(doc.uploaded_at) : "-"}
              </TableCell>
            </TableRow>
          ))
        }
      </TableBody>
    </Table>
  </CollapsibleContent>
</Collapsible>
```

**Logic**:
```typescript
function getDocumentStatusBadge(status: string): JSX.Element {
  const config = {
    missing: { variant: "destructive", label: "Chưa nộp", icon: XCircle },
    uploaded: { variant: "warning", label: "Đã tải", icon: Upload },
    verified: { variant: "success", label: "Đã xác nhận", icon: CheckCircle2 },
    rejected: { variant: "destructive", label: "Từ chối", icon: XCircle },
    paper_submitted: { variant: "secondary", label: "Nộp giấy", icon: FileText },
  }
  const c = config[status] ?? config.missing
  return (
    <Badge variant={c.variant}>
      <c.icon className="w-3 h-3 mr-1" />
      {c.label}
    </Badge>
  )
}

function getFormatLabel(format: string): string {
  const labels = {
    original: "Bản chính",
    certified_copy: "Bản sao có chứng thực",
    photo: "Bản photocopy",
  }
  return labels[format] ?? format
}

function formatDate(isoString: string): string {
  return new Date(isoString).toLocaleDateString("vi-VN")
}
```

---

### Shared Component: `HealthCheckItem`

```tsx
interface HealthCheckItemProps {
  label: string
  status: "success" | "warning" | "error" | "locked"
  errorCount?: number
}

function HealthCheckItem({ label, status, errorCount }: HealthCheckItemProps) {
  const config = {
    success: { icon: CheckCircle2, color: "text-green-600", bg: "bg-green-50" },
    warning: { icon: AlertTriangle, color: "text-amber-600", bg: "bg-amber-50" },
    error: { icon: XCircle, color: "text-red-600", bg: "bg-red-50" },
    locked: { icon: Lock, color: "text-gray-400", bg: "bg-gray-50" },
  }
  const c = config[status]

  return (
    <div className={cn("flex items-center justify-between p-2 rounded-lg", c.bg)}>
      <div className="flex items-center gap-2">
        <c.icon className={cn("w-4 h-4", c.color)} />
        <span className="text-sm">{label}</span>
      </div>
      {errorCount && errorCount > 0 && (
        <Badge variant="destructive" className="text-xs">
          {errorCount} lỗi
        </Badge>
      )}
    </div>
  )
}
```

---

## 🛠️ Implementation Plan

### Phase 1: Backend Check (Optional - CẦN XÁC NHẬN)

**Kiểm tra**: Backend có trả về `academic_program` name trong `applied_rules` không?

```python
# Backend_FastAPI/app/services/admission_service.py
# Trong hàm _compute_frontend_fields()

# CẦN THÊM (nếu chưa có):
applied_rules["academic_program_name"] = profile.lead.academic_program.name  # hoặc tương tự
```

**Action**:
- [ ] Kiểm tra backend response có `applied_rules.academic_program_name`
- [ ] Nếu chưa: Thêm field vào `_compute_frontend_fields()` hoặc hiển thị từ `lead` relationship

---

### Phase 2: Frontend Components

#### Step 1: Tạo Utility Functions

**File**: `frontend/src/lib/utils/admission-helpers.ts`

```typescript
export function getAdmissionMethodLabel(appliedRules: AppliedRules): string {
  const methodLabels: Record<string, string> = {
    HOC_BA: "Xét học bạ THPT",
    THI_THPT: "Xét điểm thi THPT",
    DGNL: "Xét điểm đánh giá năng lực",
    IELTS: "Xét chứng chỉ IELTS",
  }
  return methodLabels[appliedRules.admission_method ?? ""] ?? appliedRules.admission_method ?? "N/A"
}

export function getSubjectLabel(code: string): string {
  // ... (như trên)
}

export function getDocumentStatusBadge(status: string): JSX.Element {
  // ... (như trên)
}

// ... các helpers khác
```

#### Step 2: Tạo Sub-Components

**File**: `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/executive-summary/`

```
executive-summary/
├── ExecutiveSummaryHeader.tsx      // Section 1
├── HealthCheckGrid.tsx             // Section 2 (container)
├── LegalDocsCard.tsx               // Khối 1
├── AcademicCard.tsx                // Khối 2
├── AdminCard.tsx                   // Khối 3
├── ReviewDetails.tsx               // Section 3 (container)
├── ScoreSnapshot.tsx               // 3.1
├── DocumentChecklist.tsx           // 3.2
└── HealthCheckItem.tsx             // Shared component
```

#### Step 3: Refactor FinalizeTab.tsx

**File**: `frontend/src/app/(dashboard)/admissions/[id]/_components/tabs/FinalizeTab.tsx`

```tsx
"use client"

import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Send, Loader2 } from "lucide-react"
import { ExecutiveSummaryHeader } from "./executive-summary/ExecutiveSummaryHeader"
import { HealthCheckGrid } from "./executive-summary/HealthCheckGrid"
import { ReviewDetails } from "./executive-summary/ReviewDetails"
import type { AdmissionProfileResponse } from "@/lib/zod/admissions"

interface FinalizeTabProps {
  profile: AdmissionProfileResponse
  isEligible: boolean
  onSubmit: () => void
  isSubmitting: boolean
  canApprove: boolean
}

export function FinalizeTab({
  profile,
  isEligible,
  onSubmit,
  isSubmitting,
  canApprove
}: FinalizeTabProps) {
  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-6">
      {/* Section 1: Header */}
      <ExecutiveSummaryHeader profile={profile} />

      {/* Section 2: Health Check Grid */}
      <HealthCheckGrid profile={profile} />

      {/* Section 3: Review Details */}
      <ReviewDetails profile={profile} />

      {/* Action Buttons */}
      {canApprove && (
        <Card className="p-6">
          <div className="flex justify-center gap-4">
            <Button
              size="lg"
              variant="outline"
              disabled={isSubmitting}
            >
              Từ chối
            </Button>
            <Button
              size="lg"
              disabled={!isEligible || isSubmitting}
              onClick={onSubmit}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Đang xử lý...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4 mr-2" />
                  Phê duyệt hồ sơ
                </>
              )}
            </Button>
          </div>
        </Card>
      )}
    </div>
  )
}
```

#### Step 4: Update AdmissionDetailClient.tsx

```tsx
// Line 300: Update FinalizeTab call
{currentStep === 7 && (
  <FinalizeTab
    profile={profile}
    isEligible={isEligible}
    onSubmit={handleSubmit}
    isSubmitting={submitMutation.isPending}
    canApprove={can('approve')}
  />
)}
```

---

## 📝 Checklist Implementation

### Backend
- [ ] Kiểm tra `applied_rules` có `academic_program_name` không
- [ ] Nếu thiếu: Thêm vào `_compute_frontend_fields()`
- [ ] Test API response có đủ dữ liệu

### Frontend
- [ ] Tạo `admission-helpers.ts` với utility functions
- [ ] Tạo `ExecutiveSummaryHeader.tsx`
- [ ] Tạo `HealthCheckGrid.tsx` + 3 sub-cards
- [ ] Tạo `ReviewDetails.tsx` + 2 expandable sections
- [ ] Tạo `HealthCheckItem.tsx` shared component
- [ ] Refactor `FinalizeTab.tsx` để sử dụng components mới
- [ ] Update `AdmissionDetailClient.tsx` để pass `profile` vào FinalizeTab
- [ ] Type check: `npm run type-check`
- [ ] Test UI trên nhiều scenarios:
  - [ ] Profile đủ điều kiện
  - [ ] Profile thiếu tài liệu
  - [ ] Profile lỗi điểm
  - [ ] Profile chỉ có GPA (không có subject scores)

---

## 🎯 Success Criteria

✅ **Manager/Admin có thể**:
1. Nhìn thấy toàn bộ thông tin quan trọng của hồ sơ trong 1 màn hình
2. Xác định nhanh trạng thái: Đủ điều kiện hay không
3. Thấy rõ các vấn đề cụ thể qua Health Check Grid (3 khối màu)
4. Xem chi tiết điểm xét tuyển (Best N subjects) trong bảng rõ ràng
5. Kiểm tra checklist tài liệu với status đầy đủ
6. Ra quyết định phê duyệt/từ chối ngay trên màn hình

✅ **Technical Requirements**:
- Tuân thủ Thin Client Philosophy (không tính toán logic)
- Type-safe (TypeScript + Zod)
- Responsive design (desktop ưu tiên, tablet OK)
- Accessible (keyboard navigation, screen reader support)
- Performance: Render < 100ms (không có heavy computation)

---

## 💡 Future Enhancements (Phase 2)

1. **Export PDF**: Nút "Xuất báo cáo PDF" để in hồ sơ
2. **Comparison View**: So sánh nhiều hồ sơ side-by-side
3. **Timeline**: Lịch sử thay đổi hồ sơ (created → submitted → approved)
4. **Comments**: Manager có thể để lại ghi chú nội bộ
5. **Batch Actions**: Phê duyệt nhiều hồ sơ cùng lúc

---

## 📚 Related Documentation

- `FRONTEND_ARCHITECTURE_V3.md` - Frontend guidelines
- `MASTER_ARCHITECTURE.md` - Backend architecture
- `FINAL_IMPLEMENTATION_SUMMARY.md` - Document management implementation

---

**Prepared by**: Claude Code Assistant
**Date**: 2026-01-23
**Status**: 📋 PROPOSAL - Awaiting User Approval
