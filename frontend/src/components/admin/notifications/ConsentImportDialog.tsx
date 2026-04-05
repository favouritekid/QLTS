"use client";

/**
 * Phase B11: Consent Import Dialog — CSV upload with preview.
 *
 * Also includes a simple consent list table and single upsert form.
 */
import { useCallback, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Loader2,
  Plus,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/table/Pagination";
import {
  useBulkImportConsents,
  useNotificationConsents,
  useUpsertConsent,
  type UseNotificationConsentsParams,
} from "@/hooks/useNotificationConsents";
import type {
  NotificationConsent,
  NotificationConsentImportResult,
  NotificationConsentsPage,
} from "@/types/api.types";

// ============================================
// HELPERS
// ============================================

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const CONSENT_STATUS_CONFIG: Record<string, { label: string; variant: "default" | "destructive" }> = {
  granted: { label: "Đã cấp", variant: "default" },
  revoked: { label: "Đã thu hồi", variant: "destructive" },
};

// ============================================
// MAIN COMPONENT
// ============================================

interface ConsentManagerProps {
  initialData?: NotificationConsentsPage;
}

export default function ConsentManager({ initialData }: ConsentManagerProps) {
  // Filters
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [channelFilter, setChannelFilter] = useState("all");
  const [sourceTypeFilter, setSourceTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  // Dialogs
  const [importOpen, setImportOpen] = useState(false);
  const [upsertOpen, setUpsertOpen] = useState(false);

  const params: UseNotificationConsentsParams = {
    page,
    page_size: pageSize,
    channel: channelFilter !== "all" ? channelFilter : undefined,
    source_type: sourceTypeFilter !== "all" ? sourceTypeFilter : undefined,
    consent_status: statusFilter !== "all" ? statusFilter : undefined,
  };

  const { data, isLoading, error } = useNotificationConsents(params, {
    initialData,
  });

  const consents = data?.consents ?? [];
  const total = data?.total_count ?? 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Consent Management
          </h1>
          <p className="text-muted-foreground">
            Quản lý quyền đồng ý gửi thông báo qua kênh ngoài
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setImportOpen(true)}>
            <Upload className="mr-2 h-4 w-4" />
            Import CSV
          </Button>
          <Button onClick={() => setUpsertOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Thêm consent
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col gap-4 sm:flex-row">
            <Select value={channelFilter} onValueChange={(v) => { setChannelFilter(v); setPage(1); }}>
              <SelectTrigger className="w-[150px]">
                <SelectValue placeholder="Kênh" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả kênh</SelectItem>
                <SelectItem value="zalo">Zalo</SelectItem>
                <SelectItem value="email">Email</SelectItem>
                <SelectItem value="sms">SMS</SelectItem>
              </SelectContent>
            </Select>

            <Select value={sourceTypeFilter} onValueChange={(v) => { setSourceTypeFilter(v); setPage(1); }}>
              <SelectTrigger className="w-[170px]">
                <SelectValue placeholder="Loại nguồn" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả</SelectItem>
                <SelectItem value="lead">Lead</SelectItem>
                <SelectItem value="admission_profile">Hồ sơ TS</SelectItem>
                <SelectItem value="collaborator">CTV</SelectItem>
              </SelectContent>
            </Select>

            <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1); }}>
              <SelectTrigger className="w-[150px]">
                <SelectValue placeholder="Trạng thái" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Tất cả</SelectItem>
                <SelectItem value="granted">Đã cấp</SelectItem>
                <SelectItem value="revoked">Đã thu hồi</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Loading / Error */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && (
        <Card className="border-destructive">
          <CardContent className="flex items-center gap-3 py-4">
            <AlertCircle className="h-5 w-5 text-destructive" />
            <p className="text-sm text-destructive">
              Không thể tải dữ liệu consent: {error.message}
            </p>
          </CardContent>
        </Card>
      )}

      {/* Empty */}
      {!isLoading && !error && consents.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FileText className="h-12 w-12 text-muted-foreground/50" />
            <p className="mt-4 text-lg font-medium">Chưa có consent record</p>
            <p className="text-sm text-muted-foreground">
              Sử dụng nút &quot;Import CSV&quot; hoặc &quot;Thêm consent&quot;
              để tạo mới
            </p>
          </CardContent>
        </Card>
      )}

      {/* Table */}
      {!isLoading && consents.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Kênh</TableHead>
                  <TableHead>Loại nguồn</TableHead>
                  <TableHead>Source ID</TableHead>
                  <TableHead>SĐT / Email</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Nguồn</TableHead>
                  <TableHead>Cập nhật</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {consents.map((c: NotificationConsent) => {
                  const sc = CONSENT_STATUS_CONFIG[c.consent_status] ?? CONSENT_STATUS_CONFIG.granted;
                  return (
                    <TableRow key={c.id}>
                      <TableCell className="font-medium">{c.channel}</TableCell>
                      <TableCell>{c.source_type}</TableCell>
                      <TableCell>{c.source_id}</TableCell>
                      <TableCell className="text-sm">
                        {c.normalized_phone || c.normalized_email || "—"}
                      </TableCell>
                      <TableCell>
                        <Badge variant={sc.variant}>{sc.label}</Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {c.consent_source}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(c.updated_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
          <div className="border-t px-4 py-3">
            <Pagination
              page={page}
              pageSize={pageSize}
              total={total}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              showPageSizeSelector
              pageSizeOptions={[20, 50, 100]}
              isLoading={isLoading}
            />
          </div>
        </Card>
      )}

      {/* Import Dialog */}
      <ImportDialog open={importOpen} onOpenChange={setImportOpen} />

      {/* Single Upsert Dialog */}
      <UpsertDialog open={upsertOpen} onOpenChange={setUpsertOpen} />
    </div>
  );
}

// ============================================
// IMPORT DIALOG
// ============================================

function ImportDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<NotificationConsentImportResult | null>(null);
  const bulkImport = useBulkImportConsents();

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0] ?? null;
      setSelectedFile(f);
      setResult(null);
    },
    []
  );

  const handleImport = useCallback(async () => {
    if (!selectedFile) return;
    try {
      const res = await bulkImport.mutateAsync(selectedFile);
      setResult(res);
      toast.success(
        `Import xong: ${res.processed} xử lý, ${res.granted} cấp, ${res.revoked} thu hồi`
      );
    } catch {
      toast.error("Import thất bại. Kiểm tra lại file CSV.");
    }
  }, [selectedFile, bulkImport]);

  const handleClose = useCallback(() => {
    setSelectedFile(null);
    setResult(null);
    onOpenChange(false);
  }, [onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Import Consent từ CSV</DialogTitle>
          <DialogDescription>
            Upload file CSV với các cột bắt buộc: channel, source_type, source_id, consent_status
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* File input */}
          <div className="flex items-center gap-3">
            <Input
              ref={fileRef}
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="flex-1"
            />
          </div>

          {selectedFile && !result && (
            <p className="text-sm text-muted-foreground">
              File: {selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)
            </p>
          )}

          {/* Result summary */}
          {result && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <CheckCircle2 className="h-5 w-5 text-green-500" />
                  Kết quả import
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="grid grid-cols-2 gap-2">
                  <span>Đã xử lý:</span>
                  <span className="font-medium">{result.processed}</span>
                  <span>Đã cấp:</span>
                  <span className="font-medium text-green-600">{result.granted}</span>
                  <span>Đã thu hồi:</span>
                  <span className="font-medium text-red-600">{result.revoked}</span>
                  <span>Bỏ qua:</span>
                  <span className="font-medium text-muted-foreground">{result.skipped}</span>
                </div>

                {result.errors.length > 0 && (
                  <div className="mt-3">
                    <p className="font-medium text-destructive">
                      Lỗi ({result.errors.length}):
                    </p>
                    <ul className="mt-1 max-h-32 space-y-1 overflow-y-auto text-xs">
                      {result.errors.map((err, i) => (
                        <li key={i} className="text-destructive">
                          {err.line != null ? `Dòng ${err.line}: ` : ""}{String(err.message ?? JSON.stringify(err))}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {result ? "Đóng" : "Hủy"}
          </Button>
          {!result && (
            <Button
              onClick={handleImport}
              disabled={!selectedFile || bulkImport.isPending}
            >
              {bulkImport.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang import...
                </>
              ) : (
                <>
                  <Upload className="mr-2 h-4 w-4" />
                  Import
                </>
              )}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================
// SINGLE UPSERT DIALOG
// ============================================

function UpsertDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [channel, setChannel] = useState("zalo");
  const [sourceType, setSourceType] = useState("lead");
  const [sourceId, setSourceId] = useState("");
  const [consentStatus, setConsentStatus] = useState("granted");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [notes, setNotes] = useState("");

  const upsert = useUpsertConsent();

  const handleSubmit = useCallback(async () => {
    const sid = parseInt(sourceId, 10);
    if (isNaN(sid)) {
      toast.error("Source ID phải là số");
      return;
    }

    try {
      await upsert.mutateAsync({
        channel,
        source_type: sourceType,
        source_id: sid,
        consent_status: consentStatus,
        normalized_phone: phone || undefined,
        normalized_email: email || undefined,
        notes: notes || undefined,
      });
      toast.success("Consent đã được cập nhật");
      onOpenChange(false);
    } catch {
      toast.error("Cập nhật consent thất bại");
    }
  }, [channel, sourceType, sourceId, consentStatus, phone, email, notes, upsert, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Thêm / Cập nhật Consent</DialogTitle>
          <DialogDescription>
            Tạo hoặc cập nhật consent cho entity cụ thể
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium">Kênh</label>
              <Select value={channel} onValueChange={setChannel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="zalo">Zalo</SelectItem>
                  <SelectItem value="email">Email</SelectItem>
                  <SelectItem value="sms">SMS</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium">Trạng thái</label>
              <Select value={consentStatus} onValueChange={setConsentStatus}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="granted">Cấp quyền</SelectItem>
                  <SelectItem value="revoked">Thu hồi</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium">Loại nguồn</label>
              <Select value={sourceType} onValueChange={setSourceType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="lead">Lead</SelectItem>
                  <SelectItem value="admission_profile">Hồ sơ TS</SelectItem>
                  <SelectItem value="collaborator">CTV</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-sm font-medium">Source ID</label>
              <Input
                type="number"
                placeholder="ID"
                value={sourceId}
                onChange={(e) => setSourceId(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="text-sm font-medium">SĐT (chuẩn hóa)</label>
            <Input
              placeholder="84901234567"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          </div>

          <div>
            <label className="text-sm font-medium">Email</label>
            <Input
              type="email"
              placeholder="name@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div>
            <label className="text-sm font-medium">Ghi chú</label>
            <Input
              placeholder="Ghi chú..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Hủy
          </Button>
          <Button onClick={handleSubmit} disabled={upsert.isPending}>
            {upsert.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Đang lưu...
              </>
            ) : (
              "Lưu"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
