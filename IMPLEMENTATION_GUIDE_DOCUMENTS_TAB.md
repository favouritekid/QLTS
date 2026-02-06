# Hướng Dẫn Cập Nhật DocumentsTab.tsx

## Thay Đổi Cần Thực Hiện

### 1. Thêm State & Import

```tsx
// Thêm import
import { useResetDocument } from "@/hooks/admissions/useAdmissions"
import { RotateCcw } from "lucide-react"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"

// Thêm state trong component
const [submissionFormatDialog, setSubmissionFormatDialog] = useState<{
  isOpen: boolean
  docCode: string
  docLabel: string
  requiredFormat?: string
  action: 'upload' | 'paper'
  file?: File
} | null>(null)
const [selectedFormat, setSelectedFormat] = useState<string>("")

// Thêm hook
const resetMutation = useResetDocument(profile.id)
```

### 2. Thêm Modal Chọn Submission Format

Thêm trước closing tag `</>` cuối component:

```tsx
{/* Submission Format Selection Dialog */}
<Dialog
  open={submissionFormatDialog?.isOpen || false}
  onOpenChange={(open) => !open && setSubmissionFormatDialog(null)}
>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Xác nhận loại bản nộp</DialogTitle>
      <DialogDescription>
        Tài liệu: <strong>{submissionFormatDialog?.docLabel}</strong>
        <br />
        {submissionFormatDialog?.requiredFormat && (
          <span className="text-sm text-amber-600">
            Yêu cầu: {SUBMISSION_FORMAT_CONFIG[submissionFormatDialog.requiredFormat]?.label}
          </span>
        )}
      </DialogDescription>
    </DialogHeader>

    <RadioGroup value={selectedFormat} onValueChange={setSelectedFormat}>
      <div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-muted/50">
        <RadioGroupItem value="original" id="original" />
        <Label htmlFor="original" className="flex-1 cursor-pointer">
          <div className="font-medium">Bản chính</div>
          <div className="text-xs text-muted-foreground">
            Giấy tờ gốc do cơ quan có thẩm quyền cấp
          </div>
        </Label>
      </div>

      <div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-muted/50">
        <RadioGroupItem value="certified_copy" id="certified_copy" />
        <Label htmlFor="certified_copy" className="flex-1 cursor-pointer">
          <div className="font-medium">Bản sao có chứng thực</div>
          <div className="text-xs text-muted-foreground">
            Bản photocopy được công chứng/chứng thực
          </div>
        </Label>
      </div>

      <div className="flex items-center space-x-2 p-3 border rounded-lg hover:bg-muted/50">
        <RadioGroupItem value="photo" id="photo" />
        <Label htmlFor="photo" className="flex-1 cursor-pointer">
          <div className="font-medium">Bản photocopy</div>
          <div className="text-xs text-muted-foreground">
            Bản sao không công chứng
          </div>
        </Label>
      </div>
    </RadioGroup>

    <DialogFooter>
      <Button variant="outline" onClick={() => setSubmissionFormatDialog(null)}>
        Hủy
      </Button>
      <Button
        onClick={handleSubmissionFormatConfirm}
        disabled={!selectedFormat}
      >
        Xác nhận
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

### 3. Update handleUploadClick

```tsx
const handleUploadClick = (code: string, label: string, requiredFormat?: string) => {
  setSelectedDocCode(code)

  // Open format selection dialog
  setSubmissionFormatDialog({
    isOpen: true,
    docCode: code,
    docLabel: label,
    requiredFormat,
    action: 'upload'
  })
  setSelectedFormat(requiredFormat || "")
}
```

### 4. Update handleFileChange

```tsx
const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
  const file = e.target.files?.[0]
  if (!file || !selectedDocCode) return

  const error = validateFile(file)
  if (error) {
    toast.error(error)
    return
  }

  // Store file and wait for format selection
  if (submissionFormatDialog) {
    setSubmissionFormatDialog({
      ...submissionFormatDialog,
      file
    })
  }
}
```

### 5. Thêm Handler Confirm Format

```tsx
const handleSubmissionFormatConfirm = async () => {
  if (!submissionFormatDialog || !selectedFormat) return

  const { action, docCode, file } = submissionFormatDialog

  if (action === 'upload' && file) {
    // Upload with format
    uploadMutation.mutate({
      docCode,
      file,
      actualSubmissionFormat: selectedFormat
    })
  } else if (action === 'paper') {
    // Mark paper submitted with format
    paperMutation.mutate({
      docCode,
      actualSubmissionFormat: selectedFormat
    })
  }

  // Close dialog
  setSubmissionFormatDialog(null)
  setSelectedFormat("")
}
```

### 6. Update handlePaperSubmit

```tsx
const handlePaperSubmit = (code: string, label: string, requiredFormat?: string) => {
  // Open format selection dialog
  setSubmissionFormatDialog({
    isOpen: true,
    docCode: code,
    docLabel: label,
    requiredFormat,
    action: 'paper'
  })
  setSelectedFormat(requiredFormat || "")
}
```

### 7. Thêm Nút Reset/Undo

Trong phần actions của mỗi document, thêm:

```tsx
{/* Reset/Undo Button - Show for uploaded/paper_submitted/verified/rejected */}
{can('edit') &&
 (doc.status === "uploaded" ||
  doc.status === "paper_submitted" ||
  doc.status === "verified" ||
  doc.status === "rejected") && (
  <Button
    size="sm"
    variant="ghost"
    className="text-amber-600 hover:text-amber-700 hover:bg-amber-50"
    onClick={() => {
      if (confirm(`Hoàn tác tài liệu "${doc.label}"? Tài liệu sẽ về trạng thái "Chưa nộp".`)) {
        resetMutation.mutate(doc.code)
      }
    }}
    disabled={resetMutation.isPending}
    title="Hoàn tác (đưa về trạng thái chưa nộp)"
  >
    {resetMutation.isPending && resetMutation.variables === doc.code ? (
      <Loader2 className="h-4 w-4 animate-spin" />
    ) : (
      <RotateCcw className="h-4 w-4" />
    )}
  </Button>
)}
```

### 8. Update Button Calls

Cập nhật các nơi gọi `handleUploadClick` và checkbox:

```tsx
{/* Upload Button */}
<Button
  size="sm"
  variant="outline"
  onClick={() => handleUploadClick(doc.code, doc.label, doc.submission_format)}
  disabled={uploadMutation.isPending}
>
  ...
</Button>

{/* Paper Checkbox */}
<Checkbox
  id={`paper-${doc.code}`}
  disabled={isPaperPending}
  onCheckedChange={(checked) => {
    if (checked) handlePaperSubmit(doc.code, doc.label, doc.submission_format)
  }}
/>
```

## Kết Quả

Sau khi implement:
- ✅ Upload file → Modal chọn loại bản → Upload với format
- ✅ Đánh dấu "Đã nộp" → Modal chọn loại bản → Lưu với format
- ✅ Nút hoàn tác xuất hiện cho tài liệu đã nộp
- ✅ Click hoàn tác → Reset về "missing"
- ✅ Completion % tự động cập nhật theo step_status
