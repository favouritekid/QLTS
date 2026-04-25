"use client";

import { useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Loader2, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { useCreateAdmissionPath, useUpdateAdmissionPath } from "@/hooks/admissions/useAdmissionPaths";
import { useAuth } from "@/hooks/useAuth";
import { FIELD_GROUPS_VI, FIELD_LABELS_VI } from "@/lib/constants/minor-correction";
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
  // PR #6 — path-level submit strictness. Default strict (false) for new paths;
  // edits read the current value from backend.
  const [allowUnverified, setAllowUnverified] = useState<boolean>(
    path?.allow_unverified_submission ?? false
  );

  // Per-path minor correction allowlist. Admin-only — manager sees the
  // section disabled (server raises BusinessRuleViolation if a manager
  // tries to submit it anyway). Default empty = correction disabled.
  const [allowedFields, setAllowedFields] = useState<Set<string>>(
    new Set(path?.minor_correction_allowed_fields ?? [])
  );
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const allowedFieldsArray = useMemo(
    () => Array.from(allowedFields).sort(),
    [allowedFields]
  );

  const createMutation = useCreateAdmissionPath();
  const updateMutation = useUpdateAdmissionPath();

  function toggleField(field: string) {
    setAllowedFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) {
        next.delete(field);
      } else {
        next.add(field);
      }
      return next;
    });
  }

  const handleSave = async () => {
    if (!selectedMethodId) {
      toast.error("Vui lòng chọn phương thức tuyển sinh");
      return;
    }

    try {
      let savedId: number;

      if (path) {
        // Update existing — only admin sends the allowlist field. Server
        // raises BusinessRuleViolation if a non-admin caller submits it,
        // so the FE has to make sure it's omitted entirely for managers.
        await updateMutation.mutateAsync({
          pathId: path.id,
          data: {
            display_name: displayName || undefined,
            display_order: displayOrder,
            visibility: visibility,
            allow_unverified_submission: allowUnverified,
            ...(isAdmin
              ? { minor_correction_allowed_fields: allowedFieldsArray }
              : {}),
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
          allow_unverified_submission: allowUnverified,
          // Only admin can seed the allowlist on create. Manager
          // creating a new path always gets the empty default.
          minor_correction_allowed_fields: isAdmin ? allowedFieldsArray : [],
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

          {/* PR #6 — per-path submit strictness toggle */}
          <div className="flex items-start justify-between gap-4 rounded-md border p-3">
            <div className="space-y-1">
              <Label htmlFor="allow-unverified" className="text-sm font-medium">
                Cho phép nộp hồ sơ khi tài liệu chưa xác minh
              </Label>
              <p className="text-xs text-muted-foreground max-w-lg">
                Mặc định tắt: thí sinh chỉ nộp được khi tài liệu đã được quản
                lý xác minh (hoặc đã nhận bản giấy). Bật sẽ giữ hành vi cũ,
                chấp nhận tài liệu đang ở trạng thái &quot;đã tải lên&quot;. Các
                hồ sơ đã tạo trước đó giữ nguyên chế độ đã snapshot — chỉ hồ
                sơ tạo sau khi đổi mới áp dụng thiết lập mới.
              </p>
            </div>
            <Switch
              id="allow-unverified"
              checked={allowUnverified}
              onCheckedChange={setAllowUnverified}
              aria-label="Cho phép nộp hồ sơ khi tài liệu chưa xác minh"
            />
          </div>

          {/* Minor-correction allowlist (governance setting). Admin-only.
              Manager sees the section but inputs are disabled — server
              enforces the same gate via BusinessRuleViolation. */}
          <div className="space-y-3 rounded-md border p-3">
            <div className="space-y-1">
              <Label className="text-sm font-medium">
                Hiệu chỉnh sau duyệt — danh sách trường được phép
                {!isAdmin && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    (chỉ admin)
                  </span>
                )}
              </Label>
              <p className="text-xs text-muted-foreground max-w-lg">
                Cho phép officer/manager hiệu chỉnh các trường không ảnh
                hưởng tiêu chí xét tuyển trên hồ sơ đã duyệt/đã xác nhận.
                Chỉ các trường tick bên dưới mới hiển thị trong dialog
                hiệu chỉnh; mọi thay đổi đều bị log với lý do bắt buộc.
              </p>
            </div>
            <div className="space-y-4">
              {Object.entries(FIELD_GROUPS_VI).map(([groupName, fields]) => (
                <div key={groupName} className="space-y-2">
                  <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    {groupName}
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {fields.map((field) => (
                      <label
                        key={field}
                        className="flex items-start gap-2 text-sm cursor-pointer"
                      >
                        <Checkbox
                          id={`mc-allow-${field}`}
                          checked={allowedFields.has(field)}
                          onCheckedChange={() => toggleField(field)}
                          disabled={!isAdmin}
                          aria-label={FIELD_LABELS_VI[field] ?? field}
                        />
                        <span className="leading-tight">
                          {FIELD_LABELS_VI[field] ?? field}
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
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
