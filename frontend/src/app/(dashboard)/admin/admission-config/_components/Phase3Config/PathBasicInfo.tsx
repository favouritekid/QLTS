"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { useCreateAdmissionPath, useUpdateAdmissionPath } from "@/hooks/admissions/useAdmissionPaths";
import type { AdmissionPathResponse } from "@/lib/zod/admission-path";
import type { AdmissionMethod } from "../shared/types";
import type { AxiosError } from "axios";

interface PathBasicInfoProps {
  path?: AdmissionPathResponse;
  methods: AdmissionMethod[];
  academicInfoId: number;
  onFinish: (pathId: number) => void;
}

export function PathBasicInfo({ path, methods, academicInfoId, onFinish }: PathBasicInfoProps) {
  // Initialize state directly from props (Key-based remount ensures fresh init)
  const [displayName, setDisplayName] = useState(path?.display_name || "");
  const [selectedMethodId, setSelectedMethodId] = useState<number | null>(path?.admission_method?.id || null);
  const [displayOrder, setDisplayOrder] = useState(path?.display_order || 1);
  const [visibility, setVisibility] = useState<"public" | "internal">(path?.visibility || "internal");

  const createMutation = useCreateAdmissionPath();
  const updateMutation = useUpdateAdmissionPath();

  const handleSave = async () => {
    if (!selectedMethodId) {
      toast.error("Vui lòng chọn phương thức tuyển sinh");
      return;
    }

    try {
      let savedId: number;

      if (path) {
        // Update existing
        await updateMutation.mutateAsync({
          pathId: path.id,
          data: {
            display_name: displayName || undefined,
            display_order: displayOrder,
            visibility: visibility,
          },
        });
        savedId = path.id;
        toast.success("Cập nhật thông tin cơ bản thành công");
      } else {
        // Create new
        const newPath = await createMutation.mutateAsync({
          academic_info_id: academicInfoId,
          admission_method_id: selectedMethodId,
          display_name: displayName || undefined,
          display_order: displayOrder,
          visibility: visibility,
        });
        savedId = newPath.id;
        toast.success("Tạo đợt tuyển sinh thành công");
      }

      onFinish(savedId);
    } catch (error) {
      const axiosError = error as AxiosError<{ detail?: string }>;
      toast.error(axiosError.response?.data?.detail || "Lưu thất bại");
    }
  };

  const isSaving = createMutation.isPending || updateMutation.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Bước 1: Thông tin Cơ bản</CardTitle>
        <CardDescription>
          Chọn phương thức tuyển sinh và tên hiển thị
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="method">
              Phương thức Tuyển sinh <span className="text-destructive">*</span>
            </Label>
            <Select
              value={selectedMethodId?.toString() || ""}
              onValueChange={(value) => setSelectedMethodId(parseInt(value))}
              disabled={!!path} // Cannot change method after creation
            >
              <SelectTrigger id="method">
                <SelectValue placeholder="Chọn phương thức" />
              </SelectTrigger>
              <SelectContent>
                {methods.map((method) => (
                  <SelectItem key={method.id} value={method.id.toString()}>
                    {method.name}
                    <span className="text-muted-foreground ml-2">({method.code})</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {path && (
              <p className="text-xs text-muted-foreground">
                Không thể thay đổi phương thức sau khi tạo
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="displayName">Tên hiển thị (Tùy chọn)</Label>
            <Input
              id="displayName"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Để trống để dùng tên phương thức mặc định"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="displayOrder">Thứ tự hiển thị</Label>
            <Input
              id="displayOrder"
              type="number"
              value={displayOrder}
              onChange={(e) => setDisplayOrder(parseInt(e.target.value) || 1)}
              min={1}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="visibility">Hiển thị</Label>
            <Select
              value={visibility}
              onValueChange={(val: "public" | "internal") => setVisibility(val)}
            >
              <SelectTrigger id="visibility">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="public">Công khai</SelectItem>
                <SelectItem value="internal">Nội bộ</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Công khai: Hiển thị cho thí sinh. Nội bộ: Chỉ admin/manager thấy.
            </p>
          </div>

          <div className="flex justify-end pt-4">
            <Button onClick={handleSave} disabled={isSaving}>
              {isSaving ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <ArrowRight className="h-4 w-4 mr-2" />
              )}
              {path ? "Cập nhật & Tiếp tục" : "Tạo & Tiếp tục"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
