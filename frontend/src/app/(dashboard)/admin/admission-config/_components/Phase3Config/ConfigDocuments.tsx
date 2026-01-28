"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, ArrowLeft, Archive, AlertTriangle, Info } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { useUpdatePathDocuments, usePathDocuments } from "@/hooks/admissions/useAdmissionPaths";
import { useDocumentTypes } from "@/hooks/admissions/useMasterData";
import { AdmissionPathResponse } from "@/lib/zod/admission-path";
import type { DocumentType } from "../shared/types";

interface ConfigDocumentsProps {
  path: AdmissionPathResponse;
  onFinish: () => void;
  onBack: () => void;
}

interface DocSelection {
  document_type_id: number;
  is_mandatory: boolean;
  requires_upload: boolean;
  submission_format: string | null;
  display_order: number;
}

export function ConfigDocuments({ path, onFinish, onBack }: ConfigDocumentsProps) {
  // Queries
  const { data: allDocTypes = [], isLoading: loadingTypes } = useDocumentTypes();
  const { data: resolvedDocs, isLoading: loadingResolved } = usePathDocuments(path.id);
  const updateMutation = useUpdatePathDocuments();

  // ✅ Section 2.6.8: Derive initial selections from API data using useMemo
  const initialSelections = useMemo(() => {
    if (!resolvedDocs) return {};
    const initialMap: Record<number, DocSelection> = {};
    resolvedDocs.forEach((doc) => {
      initialMap[doc.document_type_id] = {
        document_type_id: doc.document_type_id,
        is_mandatory: doc.is_mandatory,
        requires_upload: doc.requires_upload,
        submission_format: doc.submission_format,
        display_order: doc.display_order
      };
    });
    return initialMap;
  }, [resolvedDocs]);

  // Local modifications state - starts empty, merged with initial on save
  const [modifications, setModifications] = useState<Record<number, DocSelection | null>>({});

  // Computed current selections: initial + modifications
  const selections = useMemo(() => {
    const result = { ...initialSelections };
    Object.entries(modifications).forEach(([id, mod]) => {
      const numId = Number(id);
      if (mod === null) {
        delete result[numId]; // Removed by user
      } else if (mod) {
        result[numId] = mod; // Added or updated by user
      }
    });
    return result;
  }, [initialSelections, modifications]);

  // Handlers
  const handleSelect = (typeId: number, checked: boolean) => {
    if (checked) {
      // Add new or restore from initial
      const existing = initialSelections[typeId];
      setModifications(prev => ({
        ...prev,
        [typeId]: existing ?? {
          document_type_id: typeId,
          is_mandatory: true,
          requires_upload: true,
          submission_format: null,
          display_order: Object.keys(selections).length + 1
        }
      }));
    } else {
      // Mark as removed
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
    const selectedCount = Object.keys(selections).length;

    // Validation - at least one document should be selected
    if (selectedCount === 0) {
      toast.warning("Vui lòng chọn ít nhất một loại hồ sơ");
      return;
    }

    try {
      const payload = Object.values(selections);
      console.log("ConfigDocuments: Saving payload:", payload);

      await updateMutation.mutateAsync({
        pathId: path.id,
        data: payload
      });

      toast.success(`Đã lưu cấu hình hồ sơ thành công (${selectedCount} loại)`);
      // Move to review step after successful save
      onFinish();
    } catch (error: unknown) {
      console.error("ConfigDocuments: Save error:", error);
      const apiError = error as { response?: { data?: { detail?: unknown } } };
      console.error("ConfigDocuments: Error response:", apiError?.response?.data);

      // Extract validation error details
      const errorDetail = apiError?.response?.data?.detail;
      let errorMessage = "Lưu thất bại. Vui lòng thử lại.";

      if (Array.isArray(errorDetail)) {
        interface ValidationError { loc?: string[]; msg?: string }
        errorMessage = errorDetail.map((e: ValidationError) => `${e.loc?.join('.')}: ${e.msg}`).join(", ");
      } else if (typeof errorDetail === "string") {
        errorMessage = errorDetail;
      }

      toast.error(errorMessage);
    }
  };

  const isLoading = loadingTypes || loadingResolved;
  const isSaving = updateMutation.isPending;

  // Groupdoc types for easier selection? Or just list?
  // Flat list for now
  
  // Detachment check: If ANY resolved doc has source="method_override", we are detached.
  const isDetached = resolvedDocs?.some(doc => doc.source === "method_override");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cấu hình Hồ sơ Yêu cầu</CardTitle>
        <CardDescription>
          Chọn các loại giấy tờ thí sinh cần nộp cho đợt tuyển sinh này.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        
        {/* Detachment Warning/Info */}
        {!isLoading && (
          <div className="mb-4">
            {isDetached ? (
              <Alert className="bg-info-50 text-info-900 border-info-200">
                <Info className="h-4 w-4" />
                <AlertTitle>Cấu hình riêng biệt (Forked)</AlertTitle>
                <AlertDescription>
                  Phương thức này đang sử dụng cấu hình hồ sơ riêng, không còn đồng bộ với cấu hình chung (Shared Defaults).
                </AlertDescription>
              </Alert>
            ) : (
              <Alert className="bg-warning-50 text-warning-900 border-warning-200">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Chú ý: Ghi đè cấu hình chung</AlertTitle>
                <AlertDescription>
                  Hiện tại đang sử dụng cấu hình chung. Nếu bạn điều chỉnh và <strong>Lưu</strong>, 
                  hồ sơ này sẽ tách ra (Fork) và <strong>không còn tự động cập nhật</strong> theo cấu hình chung nữa.
                </AlertDescription>
              </Alert>
            )}
          </div>
        )}
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : (
          <div className="space-y-6">
            <div className="border rounded-lg overflow-hidden">
              <div className="grid grid-cols-12 bg-muted/50 p-3 text-sm font-medium border-b">
                <div className="col-span-6">Loại giấy tờ</div>
                <div className="col-span-2 text-center">Bắt buộc</div>
                <div className="col-span-2 text-center">Yêu cầu up file</div>
                <div className="col-span-2 text-center">Thứ tự</div>
              </div>
              
              <div className="max-h-[400px] overflow-y-auto">
                {allDocTypes.map((type: DocumentType) => {
                  const isSelected = !!selections[type.id];
                  const current = selections[type.id];

                  return (
                    <div 
                      key={type.id} 
                      className={`grid grid-cols-12 p-3 items-center border-b last:border-0 hover:bg-muted ${isSelected ? 'bg-info-50/30' : ''}`}
                    >
                      <div className="col-span-6 flex items-center gap-3">
                        <Checkbox 
                          id={`doc-${type.id}`}
                          checked={isSelected}
                          onCheckedChange={(checked) => handleSelect(type.id, checked as boolean)}
                        />
                        <div className="grid gap-0.5">
                          <Label 
                            htmlFor={`doc-${type.id}`}
                            className="text-sm font-medium cursor-pointer"
                          >
                            {type.name}
                          </Label>
                          <span className="text-xs text-muted-foreground">{type.code}</span>
                        </div>
                        {isSelected && resolvedDocs?.find(d => d.document_type_id === type.id)?.source === 'shared' && (
                          <Badge variant="secondary" className="text-[10px] h-5">Mặc định</Badge>
                        )}
                      </div>

                      <div className="col-span-2 flex justify-center">
                        <Checkbox 
                          checked={current?.is_mandatory || false}
                          disabled={!isSelected}
                          onCheckedChange={(c) => handleUpdate(type.id, 'is_mandatory', c === true)}
                        />
                      </div>

                      <div className="col-span-2 flex justify-center">
                        <Checkbox 
                          checked={current?.requires_upload || false}
                          disabled={!isSelected}
                          onCheckedChange={(c) => handleUpdate(type.id, 'requires_upload', c === true)}
                        />
                      </div>
                      
                      <div className="col-span-2 flex justify-center text-xs text-muted-foreground">
                         {current?.display_order || "-"}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Actions */}
            <div className="flex justify-between pt-4">
              <Button variant="outline" onClick={onBack} disabled={isSaving}>
                <ArrowLeft className="h-4 w-4 mr-2" />
                Quay lại
              </Button>
              <Button onClick={handleSave} disabled={isSaving}>
                {isSaving ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Archive className="h-4 w-4 mr-2" />
                )}
                Lưu & Tiếp tục
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
