"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, ArrowLeft, Archive } from "lucide-react";
import { toast } from "sonner";

import { useUpdatePathDocuments, usePathDocuments } from "@/hooks/admissions/useAdmissionPaths";
import { useDocumentTypes } from "@/hooks/admissions/useMasterData";
import { AdmissionPathResponse } from "@/lib/zod/admission-path";
import { ResolvedDocumentListResponse } from "@/lib/zod/admission-path";

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

  // Local State
  const [selections, setSelections] = useState<Record<number, DocSelection>>({});

  // Initialize from resolved docs
  useEffect(() => {
    console.log("ConfigDocuments: Resolved docs loaded:", resolvedDocs);
    if (resolvedDocs) {
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
      console.log("ConfigDocuments: Initialized selections:", initialMap);
      setSelections(initialMap);
    }
  }, [resolvedDocs]);

  // Handlers
  const handleSelect = (typeId: number, checked: boolean) => {
    if (checked) {
      // Add default
      setSelections(prev => ({
        ...prev,
        [typeId]: {
          document_type_id: typeId,
          is_mandatory: true,
          requires_upload: true,
          submission_format: null,
          display_order: Object.keys(prev).length + 1
        }
      }));
    } else {
      // Remove
      setSelections(prev => {
        const next = { ...prev };
        delete next[typeId];
        return next;
      });
    }
  };

  const handleUpdate = (typeId: number, field: keyof DocSelection, value: any) => {
    setSelections(prev => ({
      ...prev,
      [typeId]: {
        ...prev[typeId],
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
    } catch (error: any) {
      console.error("ConfigDocuments: Save error:", error);
      console.error("ConfigDocuments: Error response:", error?.response?.data);

      // Extract validation error details
      const errorDetail = error?.response?.data?.detail;
      let errorMessage = "Lưu thất bại. Vui lòng thử lại.";

      if (Array.isArray(errorDetail)) {
        errorMessage = errorDetail.map((e: any) => `${e.loc?.join('.')}: ${e.msg}`).join(", ");
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
  
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cấu hình Hồ sơ Yêu cầu</CardTitle>
        <CardDescription>
          Chọn các loại giấy tờ thí sinh cần nộp cho đợt tuyển sinh này.
          <br/>
          <span className="text-xs text-muted-foreground">
            Lưu ý: Cấu hình này sẽ ghi đè cấu hình mặc định của Phương thức nếu có.
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
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
                {allDocTypes.map((type: any) => {
                  const isSelected = !!selections[type.id];
                  const current = selections[type.id];

                  return (
                    <div 
                      key={type.id} 
                      className={`grid grid-cols-12 p-3 items-center border-b last:border-0 hover:bg-slate-50 ${isSelected ? 'bg-blue-50/30' : ''}`}
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
                          onCheckedChange={(c) => handleUpdate(type.id, 'is_mandatory', c)}
                        />
                      </div>

                      <div className="col-span-2 flex justify-center">
                        <Checkbox 
                          checked={current?.requires_upload || false}
                          disabled={!isSelected}
                          onCheckedChange={(c) => handleUpdate(type.id, 'requires_upload', c)}
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
