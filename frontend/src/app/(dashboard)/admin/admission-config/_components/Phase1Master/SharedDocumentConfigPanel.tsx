"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Loader2, Save, Eye } from "lucide-react";
import {
  useOfferingTypes,
  useDocumentTypes,
  useSharedDocumentGroup,
  useUpsertSharedDocumentGroup,
  usePreviewSharedDocuments,
} from "@/hooks/admissions/useMasterData";
import { AUDIENCE_LABELS } from "@/lib/zod/admission-path";
import { getShortFormatLabel, type DocumentFormatCode } from "@/lib/utils/admission-helpers";
import { DocumentType, OfferingType } from "../shared/types";

interface DocSelection {
  document_type_id: number;
  is_mandatory: boolean;
  requires_upload: boolean;
  submission_format: string | null;
  display_order: number;
}

interface SharedDocItem {
  document_type_id: number;
  is_mandatory: boolean;
  requires_upload: boolean;
  submission_format: string | null;
  display_order: number;
}

// Sentinel cho lớp NỀN trong Select (Radix value phải là string non-empty).
const NEN = "__NEN__";

// Sentinel cho "không yêu cầu loại bản" (submission_format=null) — Radix
// Select value phải non-empty string. Cho phép officer set Gốc/Chứng thực/
// Chụp-scan trực tiếp ở màn này (trước đây bảng chỉ có Bắt buộc/Up file/Thứ tự
// → submission_format luôn NULL → cột "Yêu cầu" tab Tài liệu hiện "—").
const FMT_NONE = "__FMT_NONE__";
const FORMAT_CODES: DocumentFormatCode[] = ["original", "certified_copy", "photo"];

// Nhãn trình độ văn hóa cho dialog Xem trước (display-only, mirror BE enum).
const CULTURAL_LABELS: Record<string, string> = {
  graduated_thpt: "Đã tốt nghiệp THPT",
  completed_thpt: "Hoàn thành THPT (chưa có bằng)",
  graduated_gdtx: "Tốt nghiệp GDTX",
  graduated_thcs: "Đã tốt nghiệp THCS",
  completed_thcs: "Hoàn thành THCS (chưa có bằng)",
};

interface PreviewDoc {
  document_type_code: string;
  document_type_name: string;
  is_mandatory: boolean;
  layer_kind: string;
  applicable_audience: string[] | null;
}

/** Dialog "Xem trước theo TS" (§5b/G5) — thin-client: gửi raw cultural cho BE derive. */
function PreviewDialog({ offeringTypeId }: { offeringTypeId: number }) {
  const [open, setOpen] = useState(false);
  const [cultural, setCultural] = useState<string | null>(null);
  const previewMutation = usePreviewSharedDocuments();
  const docs: PreviewDoc[] = previewMutation.data ?? [];

  const handleCompute = () => {
    previewMutation.mutate({
      offeringTypeId,
      body: { cultural_education_level: cultural },
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Eye className="h-4 w-4 mr-2" aria-hidden="true" />
          Xem trước theo TS
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Xem trước bộ hồ sơ theo thí sinh</DialogTitle>
          <DialogDescription>
            Chọn trình độ văn hóa của thí sinh giả định — hệ thống tính bộ giấy
            tờ thực tế (lớp NỀN + lớp theo đối tượng).
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-end gap-3">
          <div className="flex-1 space-y-1">
            <Label>Trình độ văn hóa</Label>
            <Select
              value={cultural ?? undefined}
              onValueChange={(v) => setCultural(v)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Chọn trình độ..." />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(CULTURAL_LABELS).map(([code, label]) => (
                  <SelectItem key={code} value={code}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={handleCompute} disabled={previewMutation.isPending}>
            {previewMutation.isPending ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
            ) : null}
            Tính bộ hồ sơ
          </Button>
        </div>

        {previewMutation.isSuccess && (
          <div className="border rounded-lg divide-y max-h-[300px] overflow-y-auto">
            {docs.length === 0 ? (
              <p className="p-3 text-sm text-muted-foreground">
                Không có giấy tờ nào cho cấu hình này.
              </p>
            ) : (
              docs.map((d) => (
                <div
                  key={d.document_type_code}
                  className="flex items-center justify-between p-2.5 text-sm"
                >
                  <span>
                    {d.document_type_name}
                    {d.is_mandatory && (
                      <span className="text-error-600 ml-1" aria-hidden="true">
                        *
                      </span>
                    )}
                  </span>
                  {d.layer_kind === "shared_audience" && d.applicable_audience ? (
                    <Badge
                      variant="outline"
                      className="text-[10px] h-5 border-info-100 bg-info-50 text-info-700"
                    >
                      {d.applicable_audience
                        .map((a) => AUDIENCE_LABELS[a as keyof typeof AUDIENCE_LABELS] ?? a)
                        .join(", ")}
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[10px] h-5">
                      NỀN
                    </Badge>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        <DialogFooter>
          <p className="text-xs text-muted-foreground mr-auto">
            <span className="text-error-600">*</span> bắt buộc nộp.
          </p>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SharedDocumentConfigPanel() {
  // Queries
  const { data: offeringTypes = [], isLoading: loadingOfferingTypes } = useOfferingTypes();
  const { data: allDocTypes = [], isLoading: loadingDocTypes } = useDocumentTypes();

  // State
  const [selectedOfferingTypeId, setSelectedOfferingTypeId] = useState<number | null>(null);
  // feat/document-group-audience-merge §10.17: lớp đang sửa (null = NỀN).
  const [selectedAudience, setSelectedAudience] = useState<string | null>(null);

  // Dependent Query — theo (offering_type, audience).
  const {
    data: sharedGroup,
    isLoading: loadingSharedGroup,
  } = useSharedDocumentGroup(selectedOfferingTypeId, selectedAudience);

  // Khi sửa lớp audience: fetch lớp NỀN để KHÓA giấy nền (đã kế thừa) — admin
  // chỉ thêm giấy đặc thù theo đối tượng, KHÔNG ghi trùng giấy nền vào lớp
  // (tránh redundancy: giấy nền ở 2 group → drift khi sửa NỀN sau này +
  // storefront §9 over-list). Không fetch khi đang ở chính lớp NỀN.
  const isLayerView = selectedAudience !== null;
  const { data: nenGroup } = useSharedDocumentGroup(
    isLayerView ? selectedOfferingTypeId : null,
    null,
  );
  const nenItemsByType = useMemo(() => {
    const map: Record<number, SharedDocItem> = {};
    (nenGroup?.items ?? []).forEach((item: SharedDocItem) => {
      map[item.document_type_id] = item;
    });
    return map;
  }, [nenGroup]);

  const upsertMutation = useUpsertSharedDocumentGroup();

  // ✅ Section 2.6.8: Derive initial selections from API data using useMemo
  const initialSelections = useMemo(() => {
    if (!sharedGroup?.items) return {};
    const initialMap: Record<number, DocSelection> = {};
    sharedGroup.items.forEach((item: SharedDocItem) => {
      initialMap[item.document_type_id] = {
        document_type_id: item.document_type_id,
        is_mandatory: item.is_mandatory,
        requires_upload: item.requires_upload,
        submission_format: item.submission_format,
        display_order: item.display_order
      };
    });
    return initialMap;
  }, [sharedGroup]);

  // Local modifications state - tracks user changes
  const [modifications, setModifications] = useState<Record<number, DocSelection | null>>({});

  // Reset modifications khi đổi offering type HOẶC audience (sửa lớp khác).
  const ctxKey = `${selectedOfferingTypeId}|${selectedAudience ?? NEN}`;
  const [lastCtxKey, setLastCtxKey] = useState<string | null>(null);
  if (ctxKey !== lastCtxKey) {
    setLastCtxKey(ctxKey);
    setModifications({});
  }

  // Computed current selections: initial + modifications
  const selections = useMemo(() => {
    const result = { ...initialSelections };
    Object.entries(modifications).forEach(([id, mod]) => {
      const numId = Number(id);
      if (mod === null) {
        delete result[numId];
      } else if (mod) {
        result[numId] = mod;
      }
    });
    return result;
  }, [initialSelections, modifications]);

  // Handlers
  const handleSelect = (typeId: number, checked: boolean) => {
    // Giấy NỀN trong view lớp audience = khóa (kế thừa), không toggle.
    if (isLayerView && nenItemsByType[typeId]) return;
    if (checked) {
      const existing = initialSelections[typeId];
      setModifications(prev => {
        if (existing) {
          // Omit key qua destructure (restore từ initialSelections).
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          const { [typeId]: _removed, ...rest } = prev;
          return rest;
        }
        const currentActiveCount = Object.keys(initialSelections).length
          + Object.values(prev).filter(v => v !== null).length;
        return { ...prev, [typeId]: { document_type_id: typeId, is_mandatory: true, requires_upload: true, submission_format: null, display_order: currentActiveCount + 1 } };
      });
    } else {
      setModifications(prev => ({
        ...prev,
        [typeId]: null
      }));
    }
  };

  const handleUpdate = <K extends keyof DocSelection>(typeId: number, field: K, value: DocSelection[K]) => {
    const current = selections[typeId];
    if (!current) return;

    setModifications(prev => ({
      ...prev,
      [typeId]: {
        ...current,
        [field]: value
      }
    }));
  };

  const handleSave = async () => {
    if (!selectedOfferingTypeId) return;

    try {
      // Loại giấy NỀN khỏi payload lớp audience (chỉ giữ giấy đặc thù) — tránh
      // ghi trùng giấy nền vào lớp + tự dọn nếu lớp từng lưu nhầm trước đây.
      const payload = Object.values(selections).filter(
        (s) => !(isLayerView && nenItemsByType[s.document_type_id]),
      );
      await upsertMutation.mutateAsync({
        offeringTypeId: selectedOfferingTypeId,
        data: { items: payload },
        audience: selectedAudience,
      });
      setModifications({});
    } catch {
      // Error handled by hook
    }
  };

  const isLoading = loadingOfferingTypes || loadingDocTypes;

  if (isLoading) {
    return (
      <div className="flex justify-center p-8">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const audienceLabel =
    selectedAudience === null
      ? "NỀN (mọi thí sinh)"
      : AUDIENCE_LABELS[selectedAudience as keyof typeof AUDIENCE_LABELS] ?? selectedAudience;

  return (
    <div className="space-y-6">
      {/* 1. Bộ lọc lớp: Loại hình + Đối tượng + Xem trước */}
      <div className="flex flex-wrap items-end gap-4 p-4 border rounded-lg bg-muted">
        <div className="space-y-1">
          <Label>Loại hình đào tạo</Label>
          <Select
            value={selectedOfferingTypeId?.toString()}
            onValueChange={(val) => setSelectedOfferingTypeId(Number(val))}
          >
            <SelectTrigger className="w-[260px]">
              <SelectValue placeholder="Chọn loại hình đào tạo..." />
            </SelectTrigger>
            <SelectContent>
              {offeringTypes.map((type: OfferingType) => (
                <SelectItem key={type.id} value={type.id.toString()}>
                  {type.name} ({type.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label>Đối tượng / trình độ</Label>
          <Select
            value={selectedAudience ?? NEN}
            onValueChange={(v) => setSelectedAudience(v === NEN ? null : v)}
          >
            <SelectTrigger className="w-[220px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NEN}>NỀN (mọi thí sinh)</SelectItem>
              {Object.entries(AUDIENCE_LABELS).map(([code, label]) => (
                <SelectItem key={code} value={code}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {selectedOfferingTypeId && (
          <div className="ml-auto">
            {/* key remount → reset mutation result + cultural khi đổi loại hình
                (review P2: tránh giữ kết quả preview của loại hình trước). */}
            <PreviewDialog
              key={selectedOfferingTypeId}
              offeringTypeId={selectedOfferingTypeId}
            />
          </div>
        )}
      </div>

      {/* 2. Config Area */}
      {selectedOfferingTypeId ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              Cấu hình lớp giấy tờ
              <Badge variant={selectedAudience === null ? "secondary" : "outline"}>
                {audienceLabel}
              </Badge>
            </CardTitle>
            <CardDescription>
              {selectedAudience === null
                ? "Lớp NỀN — luôn gộp cho MỌI thí sinh thuộc loại hình này."
                : `Chỉ áp dụng cho thí sinh thuộc đối tượng "${audienceLabel}". Giấy NỀN hiển thị mờ + khóa (đã kế thừa) — chỉ cần chọn thêm giấy đặc thù.`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loadingSharedGroup ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-6">
                <div className="border rounded-lg overflow-hidden">
                  <div className="grid grid-cols-12 bg-muted/50 p-3 text-sm font-medium border-b">
                    <div className="col-span-4">Loại giấy tờ</div>
                    <div className="col-span-2 text-center">Bắt buộc</div>
                    <div className="col-span-2 text-center">Yêu cầu up file</div>
                    <div className="col-span-3 text-center">Loại bản</div>
                    <div className="col-span-1 text-center">Thứ tự</div>
                  </div>

                  <div className="max-h-[500px] overflow-y-auto">
                    {allDocTypes.map((type: DocumentType) => {
                      // Giấy NỀN khi đang sửa lớp audience = kế thừa, hiển thị
                      // KHÓA (checked + disabled) để admin hiểu "đối tượng này
                      // đã có giấy nền, chỉ chọn thêm giấy đặc thù".
                      const nenItem = isLayerView ? nenItemsByType[type.id] : undefined;
                      const isInheritedNen = !!nenItem;
                      const isSelected = isInheritedNen || !!selections[type.id];
                      const current = selections[type.id];

                      const mandatoryChecked = nenItem
                        ? nenItem.is_mandatory
                        : current?.is_mandatory || false;
                      const uploadChecked = nenItem
                        ? nenItem.requires_upload
                        : current?.requires_upload || false;
                      const orderText = nenItem
                        ? nenItem.display_order
                        : current?.display_order || "-";
                      const formatValue = nenItem
                        ? nenItem.submission_format
                        : current?.submission_format ?? null;

                      return (
                        <div
                          key={type.id}
                          className={`grid grid-cols-12 p-3 items-center border-b last:border-0 hover:bg-muted ${
                            isInheritedNen
                              ? 'bg-muted/40 opacity-75'
                              : isSelected
                                ? 'bg-info-50/50'
                                : ''
                          }`}
                        >
                          <div className="col-span-4 flex items-center gap-3">
                            <Checkbox
                              id={`doc-${type.id}`}
                              checked={isSelected}
                              disabled={isInheritedNen}
                              onCheckedChange={(checked) => handleSelect(type.id, checked as boolean)}
                            />
                            <div className="grid gap-0.5">
                              <Label
                                htmlFor={`doc-${type.id}`}
                                className={`text-sm font-medium ${isInheritedNen ? '' : 'cursor-pointer'}`}
                              >
                                {type.name}
                              </Label>
                              <span className="text-xs text-muted-foreground">{type.code}</span>
                            </div>
                            {isInheritedNen && (
                              <Badge variant="secondary" className="text-[10px] h-5">
                                NỀN (kế thừa)
                              </Badge>
                            )}
                          </div>

                          <div className="col-span-2 flex justify-center">
                            <Checkbox
                              checked={mandatoryChecked}
                              disabled={isInheritedNen || !isSelected}
                              onCheckedChange={(c) => handleUpdate(type.id, 'is_mandatory', c === true)}
                            />
                          </div>

                          <div className="col-span-2 flex justify-center">
                            <Checkbox
                              checked={uploadChecked}
                              disabled={isInheritedNen || !isSelected}
                              onCheckedChange={(c) => handleUpdate(type.id, 'requires_upload', c === true)}
                            />
                          </div>

                          <div className="col-span-3 flex justify-center">
                            <Select
                              value={formatValue ?? FMT_NONE}
                              disabled={isInheritedNen || !isSelected}
                              onValueChange={(v) =>
                                handleUpdate(
                                  type.id,
                                  'submission_format',
                                  v === FMT_NONE ? null : v,
                                )
                              }
                            >
                              <SelectTrigger
                                className="h-8 w-full"
                                aria-label={`Loại bản giấy ${type.name}`}
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value={FMT_NONE}>Không yêu cầu</SelectItem>
                                {FORMAT_CODES.map((code) => (
                                  <SelectItem key={code} value={code}>
                                    {getShortFormatLabel(code)}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>

                          <div className="col-span-1 flex justify-center text-xs text-muted-foreground">
                             {orderText}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="flex justify-end pt-4">
                  <Button onClick={handleSave} disabled={upsertMutation.isPending}>
                    {upsertMutation.isPending ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4 mr-2" />
                    )}
                    Lưu lớp “{audienceLabel}”
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col items-center justify-center p-12 border-2 border-dashed rounded-lg text-muted-foreground bg-muted">
          <p>Vui lòng chọn loại hình đào tạo để cấu hình</p>
        </div>
      )}
    </div>
  );
}
