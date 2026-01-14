"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import { useOfferingTypes, useDocumentTypes, useSharedDocumentGroup, useUpsertSharedDocumentGroup } from "@/hooks/admissions/useMasterData";
import { DocumentType, OfferingType } from "../shared/types";

interface DocSelection {
  document_type_id: number;
  is_mandatory: boolean;
  requires_upload: boolean;
  submission_format: string | null;
  display_order: number;
}

export function SharedDocumentConfigPanel() {
  // Queries
  const { data: offeringTypes = [], isLoading: loadingOfferingTypes } = useOfferingTypes();
  const { data: allDocTypes = [], isLoading: loadingDocTypes } = useDocumentTypes();
  
  // State
  const [selectedOfferingTypeId, setSelectedOfferingTypeId] = useState<number | null>(null);
  
  // Dependent Query
  const { 
    data: sharedGroup, 
    isLoading: loadingSharedGroup 
  } = useSharedDocumentGroup(selectedOfferingTypeId);
  
  const upsertMutation = useUpsertSharedDocumentGroup();

  // Local Selection State
  const [selections, setSelections] = useState<Record<number, DocSelection>>({});

  // Sync state with fetched data
  useEffect(() => {
    if (sharedGroup?.items) {
      const initialMap: Record<number, DocSelection> = {};
      sharedGroup.items.forEach((item: any) => {
        initialMap[item.document_type_id] = {
          document_type_id: item.document_type_id,
          is_mandatory: item.is_mandatory,
          requires_upload: item.requires_upload,
          submission_format: item.submission_format,
          display_order: item.display_order
        };
      });
      setSelections(initialMap);
    } else if (selectedOfferingTypeId && !loadingSharedGroup) {
      // If loaded but no group exists, reset selections
      setSelections({});
    }
  }, [sharedGroup, selectedOfferingTypeId, loadingSharedGroup]);

  // Handlers
  const handleSelect = (typeId: number, checked: boolean) => {
    if (checked) {
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
    if (!selectedOfferingTypeId) return;
    
    try {
      const payload = Object.values(selections);
      await upsertMutation.mutateAsync({
        offeringTypeId: selectedOfferingTypeId,
        data: { items: payload }
      });
      // Toast handled by hook
    } catch (error) {
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

  return (
    <div className="space-y-6">
      {/* 1. Select Offering Type */}
      <div className="flex items-center gap-4 p-4 border rounded-lg bg-slate-50">
        <Label className="w-32">Loại hình đào tạo:</Label>
        <Select 
          value={selectedOfferingTypeId?.toString()} 
          onValueChange={(val) => setSelectedOfferingTypeId(Number(val))}
        >
          <SelectTrigger className="w-[300px]">
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

      {/* 2. Config Area */}
      {selectedOfferingTypeId ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Cấu hình hồ sơ dùng chung</CardTitle>
            <CardDescription>
              Các loại giấy tờ được chọn ở đây sẽ tự động áp dụng cho tất cả Phương thức xét tuyển thuộc loại hình đào tạo này.
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
                    <div className="col-span-6">Loại giấy tờ</div>
                    <div className="col-span-2 text-center">Bắt buộc</div>
                    <div className="col-span-2 text-center">Yêu cầu up file</div>
                    <div className="col-span-2 text-center">Thứ tự</div>
                  </div>
                  
                  <div className="max-h-[500px] overflow-y-auto">
                    {allDocTypes.map((type: DocumentType) => {
                      const isSelected = !!selections[type.id];
                      const current = selections[type.id];

                      return (
                        <div 
                          key={type.id} 
                          className={`grid grid-cols-12 p-3 items-center border-b last:border-0 hover:bg-slate-50 ${isSelected ? 'bg-blue-50/50' : ''}`}
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

                <div className="flex justify-end pt-4">
                  <Button onClick={handleSave} disabled={upsertMutation.isPending}>
                    {upsertMutation.isPending ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4 mr-2" />
                    )}
                    Lưu cấu hình
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col items-center justify-center p-12 border-2 border-dashed rounded-lg text-muted-foreground bg-slate-50">
          <p>Vui lòng chọn loại hình đào tạo để cấu hình</p>
        </div>
      )}
    </div>
  );
}
