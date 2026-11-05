"use client"

import { useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import {
  useCouncilTemplates,
  useUploadCouncilTemplate,
} from "@/hooks/admin/useCouncilDocuments"
import {
  COUNCIL_TEMPLATE_KINDS,
  type CouncilTemplateKind,
} from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { kichThuoc, ngay, nguoi, nhanLoaiMau, shaRutGon, thoiDiem } from "./hien-thi"

/** Kho mẫu: danh sách (cờ `xem_mau`) + tải mẫu mới (cờ `tai_mau_len`). */
export function CouncilTemplatePanel({ canUpload }: { canUpload: boolean }) {
  const q = useCouncilTemplates(true)
  return (
    <div className="space-y-6">
      {canUpload ? <UploadTemplateForm /> : null}
      {q.isPending ? (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Đang tải kho mẫu…
        </div>
      ) : q.isError ? (
        <CouncilErrorAlert error={q.error} testId="template-list-error" />
      ) : q.data.length === 0 ? (
        <p className="text-muted-foreground" data-testid="template-list-empty">
          Kho mẫu chưa có mẫu nào.
        </p>
      ) : (
        <Table data-testid="template-list">
          <TableHeader>
            <TableRow>
              <TableHead>Loại</TableHead>
              <TableHead>Hiệu lực từ</TableHead>
              <TableHead>sha256</TableHead>
              <TableHead className="text-right">Kích thước</TableHead>
              <TableHead>Người tải</TableHead>
              <TableHead>Tải lúc</TableHead>
              <TableHead>Ghi chú</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {q.data.map((m) => (
              <TableRow key={m.id} data-testid={`template-row-${m.id}`}>
                <TableCell>{nhanLoaiMau(m.loai)}</TableCell>
                <TableCell>{ngay(m.hieu_luc_tu)}</TableCell>
                <TableCell className="font-mono text-xs" title={m.sha256}>
                  {shaRutGon(m.sha256)}
                </TableCell>
                <TableCell className="text-right">{kichThuoc(m.kich_thuoc)}</TableCell>
                <TableCell>{nguoi(m.nguoi_tai_id)}</TableCell>
                <TableCell>{thoiDiem(m.tai_luc)}</TableCell>
                <TableCell className="max-w-xs whitespace-pre-line">{m.ghi_chu ?? ""}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}

function UploadTemplateForm() {
  const tai = useUploadCouncilTemplate()
  const [loai, setLoai] = useState<CouncilTemplateKind | "">("")
  const [hieuLuc, setHieuLuc] = useState("")
  const [ghiChu, setGhiChu] = useState("")
  const [tep, setTep] = useState<File | null>(null)
  const oTep = useRef<HTMLInputElement>(null)
  const guiDuoc = loai !== "" && hieuLuc !== "" && tep !== null && !tai.isPending

  return (
    <form
      className="space-y-3 rounded-md border p-4"
      data-testid="upload-template-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (loai === "" || hieuLuc === "" || tep === null || tai.isPending) return
        tai.mutate(
          { loai, hieu_luc_tu: hieuLuc, ghi_chu: ghiChu.trim() || undefined, file: tep },
          {
            onSuccess: (m) => {
              toast.success(`Đã tải mẫu ${nhanLoaiMau(m.loai)} hiệu lực từ ${ngay(m.hieu_luc_tu)}.`)
              setTep(null)
              setGhiChu("")
              if (oTep.current) oTep.current.value = ""
            },
          },
        )
      }}
    >
      <h3 className="font-semibold">Tải mẫu mới</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="space-y-1">
          <Label htmlFor="mau-loai">Loại mẫu</Label>
          <Select value={loai} onValueChange={(v) => setLoai(v as CouncilTemplateKind)}>
            <SelectTrigger id="mau-loai" data-testid="upload-loai">
              <SelectValue placeholder="Chọn loại" />
            </SelectTrigger>
            <SelectContent>
              {COUNCIL_TEMPLATE_KINDS.map((k) => (
                <SelectItem key={k} value={k}>
                  {nhanLoaiMau(k)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="mau-hieu-luc">Hiệu lực từ ngày</Label>
          <Input
            id="mau-hieu-luc"
            type="date"
            data-testid="upload-hieu-luc"
            value={hieuLuc}
            onChange={(e) => setHieuLuc(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="mau-tep">Tệp mẫu Word (.docx)</Label>
          <Input
            id="mau-tep"
            ref={oTep}
            type="file"
            data-testid="upload-file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={(e) => setTep(e.target.files?.[0] ?? null)}
          />
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="mau-ghi-chu">Ghi chú (tuỳ chọn)</Label>
        <Textarea
          id="mau-ghi-chu"
          data-testid="upload-ghi-chu"
          value={ghiChu}
          onChange={(e) => setGhiChu(e.target.value)}
        />
      </div>
      <CouncilErrorAlert error={tai.error} testId="upload-template-error" />
      <Button type="submit" disabled={!guiDuoc} data-testid="upload-template-submit">
        {tai.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Tải mẫu lên
      </Button>
    </form>
  )
}
