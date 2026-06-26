"use client"

import { Download, Eye, Loader2, Upload } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  useDownloadPaymentImportTemplate,
  usePreviewPaymentImport,
} from "@/hooks/finance/usePaymentImport"
import {
  paymentImportPreviewFormSchema,
  type PaymentImportPreview,
} from "@/lib/zod/payment-import"

const ACCEPT = ".xlsx,.csv"
const MAX_BYTES = 8 * 1024 * 1024 // khớp backend _MAX_IMPORT_FILE_BYTES

interface Props {
  onPreview: (preview: PaymentImportPreview) => void
}

export function PaymentImportUploadCard({ onPreview }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [academicYear, setAcademicYear] = useState<string>(
    String(new Date().getFullYear()),
  )
  const [semesterNo, setSemesterNo] = useState<string>("1")
  const fileInputRef = useRef<HTMLInputElement>(null)

  const download = useDownloadPaymentImportTemplate()
  const preview = usePreviewPaymentImport()

  const handlePickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    if (f && f.size > MAX_BYTES) {
      toast.error("File vượt giới hạn 8MB")
      e.target.value = ""
      return
    }
    setFile(f)
  }

  const handlePreview = () => {
    if (!file) {
      toast.error("Vui lòng chọn file .xlsx hoặc .csv")
      return
    }
    const parsed = paymentImportPreviewFormSchema.safeParse({
      academic_year: academicYear,
      semester_no: semesterNo,
    })
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Năm học / học kỳ không hợp lệ")
      return
    }
    preview.mutate(
      {
        file,
        academicYear: parsed.data.academic_year,
        semesterNo: parsed.data.semester_no,
      },
      { onSuccess: onPreview },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Import thu học phí hàng loạt</CardTitle>
        <CardDescription>
          Tải file mẫu → điền số tiền đã thu offline → tải lên để hệ thống đối
          chiếu và tự xác minh. Cột CCCD + Mã tham chiếu định dạng TEXT (giữ số 0
          đầu). Số tiền là GỐC học phí.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Tải file mẫu */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-muted-foreground">
            File mẫu:
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={download.isPending}
            onClick={() => download.mutate("xlsx")}
          >
            <Download className="mr-1.5 h-4 w-4" />
            Tải mẫu Excel
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={download.isPending}
            onClick={() => download.mutate("csv")}
          >
            <Download className="mr-1.5 h-4 w-4" />
            Tải mẫu CSV
          </Button>
        </div>

        {/* Cấp lô: năm + kỳ */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="academic-year">Năm học</Label>
            <Input
              id="academic-year"
              type="number"
              min={2020}
              max={2100}
              value={academicYear}
              onChange={(e) => setAcademicYear(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="semester">Học kỳ</Label>
            <Select value={semesterNo} onValueChange={setSemesterNo}>
              <SelectTrigger id="semester">
                <SelectValue placeholder="Chọn học kỳ" />
              </SelectTrigger>
              <SelectContent>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((s) => (
                  <SelectItem key={s} value={String(s)}>
                    Học kỳ {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Chọn file */}
        <div className="space-y-1.5">
          <Label>File thu học phí (.xlsx / .csv)</Label>
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              onChange={handlePickFile}
              className="hidden"
            />
            <Button
              type="button"
              variant="secondary"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="mr-1.5 h-4 w-4" />
              Chọn file
            </Button>
            <span className="truncate text-sm text-muted-foreground">
              {file?.name ?? "Chưa chọn file"}
            </span>
          </div>
        </div>

        <Button
          type="button"
          onClick={handlePreview}
          disabled={preview.isPending || !file}
        >
          {preview.isPending ? (
            <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
          ) : (
            <Eye className="mr-1.5 h-4 w-4" />
          )}
          Xem trước (dry-run)
        </Button>
      </CardContent>
    </Card>
  )
}
