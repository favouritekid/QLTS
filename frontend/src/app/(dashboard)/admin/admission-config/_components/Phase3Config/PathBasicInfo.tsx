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
import {
  AUDIENCE_LABELS_VI,
  AUDIENCE_OPTIONS,
} from "@/lib/constants/admission-audience";
import { FIELD_GROUPS_VI, FIELD_LABELS_VI } from "@/lib/constants/minor-correction";
import type {
  AdmissionAudience,
  AdmissionPathResponse,
  BonusRuleOverride,
} from "@/lib/zod/admission-path";
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

  // phase1_03 (#184 Wave 1 PR-1B'-FE) — audience filter. Multi-select
  // checkbox grid (5 element enum); empty Set = NULL on the wire =
  // applicable to every audience (Phase 1+2 contract, see
  // ``frontend/src/lib/zod/admission-path.ts`` and PLAN line 2649-2655).
  const [applicableTo, setApplicableTo] = useState<Set<AdmissionAudience>>(
    new Set(path?.applicable_to ?? [])
  );

  // phase1_03 — per-method quota tier. Empty input → null on wire =
  // no method-level cap. ``string`` state lets the user clear the
  // input without it snapping back to 0; we coerce on save.
  const [methodQuotaInput, setMethodQuotaInput] = useState<string>(
    path?.method_quota != null ? String(path.method_quota) : ""
  );

  // phase1_02 wired in PR-1B'-FE — typed bonus_rule_override (NOT raw
  // JSON editor per Codex P2). Admin first toggles whether to override
  // the method default at all; only when toggle is ON do the 3 sub-
  // fields appear. Toggle OFF → null on wire = inherit method default.
  const [bonusOverrideEnabled, setBonusOverrideEnabled] = useState<boolean>(
    path?.bonus_rule_override != null
  );
  const [applyAreaBonus, setApplyAreaBonus] = useState<boolean>(
    path?.bonus_rule_override?.apply_area_bonus ?? false
  );
  const [applySubjectBonus, setApplySubjectBonus] = useState<boolean>(
    path?.bonus_rule_override?.apply_subject_bonus ?? false
  );
  const [maxTotalBonusInput, setMaxTotalBonusInput] = useState<string>(
    path?.bonus_rule_override?.max_total_bonus != null
      ? String(path.bonus_rule_override.max_total_bonus)
      : ""
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

  function toggleAudience(audience: AdmissionAudience) {
    setApplicableTo((prev) => {
      const next = new Set(prev);
      if (next.has(audience)) {
        next.delete(audience);
      } else {
        next.add(audience);
      }
      return next;
    });
  }

  /**
   * Build the wire payload for ``applicable_to``.
   *
   * Empty Set → ``null`` (NULL on the wire = applicable to every
   * audience). Backend treats null and missing-key the same on
   * Create (default = null); Update uses ``model_dump(exclude_unset=
   * True)`` so we always send the key explicitly to make the
   * "clear filter" semantic unambiguous.
   */
  function buildApplicableToPayload(): AdmissionAudience[] | null {
    return applicableTo.size > 0 ? Array.from(applicableTo) : null;
  }

  /**
   * Build the wire payload for ``method_quota``.
   *
   * BE column is ``Integer`` and Pydantic ``ge=0``. Floor decimal
   * input (e.g. ``"1.5"`` → ``1``) so the BE doesn't reject the
   * payload with a Pydantic ValidationError 400. Negative or
   * non-numeric input → null (admin's intent is "clear the cap").
   */
  function buildMethodQuotaPayload(): number | null {
    if (methodQuotaInput.trim() === "") return null;
    const parsed = Number(methodQuotaInput);
    if (!Number.isFinite(parsed) || parsed < 0) return null;
    return Math.floor(parsed);
  }

  /**
   * Build the wire payload for ``bonus_rule_override``.
   *
   * Toggle OFF → null (= inherit method default). Toggle ON →
   * full 3-field shape; ``max_total_bonus`` empty → null (no cap).
   *
   * Range guard: BE Pydantic shape has ``ge=0, le=10``. We clamp
   * (rather than reject + null) because admin's intent at the UI
   * boundary is "I typed 11.5, please cap me", not "drop the cap
   * entirely". Clamping keeps the form auto-correcting; admins
   * who really want NULL clear the input.
   */
  function buildBonusOverridePayload(): BonusRuleOverride | null {
    if (!bonusOverrideEnabled) return null;
    const trimmed = maxTotalBonusInput.trim();
    let maxTotal: number | null;
    if (trimmed === "") {
      maxTotal = null;
    } else {
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed)) {
        maxTotal = null;
      } else {
        // Clamp into [0, 10] — BE Pydantic enforces the same range.
        maxTotal = Math.min(10, Math.max(0, parsed));
      }
    }
    return {
      apply_area_bonus: applyAreaBonus,
      apply_subject_bonus: applySubjectBonus,
      max_total_bonus: maxTotal,
    };
  }

  const handleSave = async () => {
    if (!selectedMethodId) {
      toast.error("Vui lòng chọn phương thức tuyển sinh");
      return;
    }

    try {
      let savedId: number;

      // phase1_03 (#184 Wave 1 PR-1B'-FE) — 3 new path fields. Admin-
      // only governance same as ``minor_correction_allowed_fields``:
      // server rejects non-admin submission via BusinessRuleViolation,
      // so the FE has to omit the keys entirely for managers. Treat
      // bonus_rule_override identically to the allowlist field.
      const applicableToPayload = buildApplicableToPayload();
      const methodQuotaPayload = buildMethodQuotaPayload();
      const bonusOverridePayload = buildBonusOverridePayload();

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
              ? {
                  minor_correction_allowed_fields: allowedFieldsArray,
                  applicable_to: applicableToPayload,
                  method_quota: methodQuotaPayload,
                  bonus_rule_override: bonusOverridePayload,
                }
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
          // Same admin-only governance for the phase1_03 fields.
          // Manager creating a new path gets nulls (= legacy / no
          // method cap / inherit method bonus default).
          applicable_to: isAdmin ? applicableToPayload : null,
          method_quota: isAdmin ? methodQuotaPayload : null,
          bonus_rule_override: isAdmin ? bonusOverridePayload : null,
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

          {/* phase1_03 (#184 Wave 1 PR-1B'-FE) — Audience filter.
              Empty selection = applicable to every audience (Phase 1+2
              contract). Admin-only same as minor_correction_allowed_fields. */}
          <div className="space-y-3 rounded-md border p-3">
            <div className="space-y-1">
              <Label className="text-sm font-medium">
                Đối tượng áp dụng
                {!isAdmin && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    (chỉ admin)
                  </span>
                )}
              </Label>
              <p className="text-xs text-muted-foreground max-w-lg">
                Chọn nhóm thí sinh có thể đăng ký path này. Bỏ trống tất
                cả = áp dụng cho mọi đối tượng (mặc định mùa cũ); admin
                tick từng đối tượng để bật bộ lọc theo trình độ ứng tuyển.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {AUDIENCE_OPTIONS.map((audience) => (
                <label
                  key={audience}
                  className="flex items-start gap-2 text-sm cursor-pointer"
                >
                  <Checkbox
                    id={`audience-${audience}`}
                    checked={applicableTo.has(audience)}
                    onCheckedChange={() => toggleAudience(audience)}
                    disabled={!isAdmin}
                    aria-label={AUDIENCE_LABELS_VI[audience]}
                  />
                  <span className="leading-tight">
                    {AUDIENCE_LABELS_VI[audience]}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* phase1_03 — Method quota. Nullable integer; empty input =
              no method-level cap, fall back to round.admit_quota
              (Phase 2) or group_quota. */}
          <div className="space-y-2 rounded-md border p-3">
            <div className="space-y-1">
              <Label htmlFor="methodQuota" className="text-sm font-medium">
                Chỉ tiêu phương thức
                {!isAdmin && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    (chỉ admin)
                  </span>
                )}
              </Label>
              <p className="text-xs text-muted-foreground max-w-lg">
                Số lượng tối đa thí sinh được tuyển qua phương thức này
                trong path. Để trống = không giới hạn ở tầng phương thức
                (sẽ kế thừa từ chỉ tiêu đợt tuyển sinh ở Phase 2).
              </p>
            </div>
            <Input
              id="methodQuota"
              type="number"
              value={methodQuotaInput}
              onChange={(e) => setMethodQuotaInput(e.target.value)}
              min={0}
              placeholder="Để trống nếu không giới hạn"
              disabled={!isAdmin}
            />
          </div>

          {/* phase1_02 wired in PR-1B'-FE — typed bonus_rule_override.
              NEVER raw JSON editor per Codex P2 review on PR-1B'-BE:
              the structured form rejects malformed shapes at the form
              boundary instead of surfacing them as Pydantic
              ValidationError 400 from the API. */}
          <div className="space-y-3 rounded-md border p-3">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <Label className="text-sm font-medium">
                  Quy tắc cộng điểm tùy chỉnh
                  {!isAdmin && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      (chỉ admin)
                    </span>
                  )}
                </Label>
                <p className="text-xs text-muted-foreground max-w-lg">
                  Tắt = path này dùng quy tắc cộng điểm mặc định của phương
                  thức. Bật để override: tích cộng điểm khu vực và/hoặc cộng
                  điểm môn ưu tiên, đặt trần tổng cộng điểm (0..10) — bỏ
                  trống trần = không giới hạn.
                </p>
              </div>
              <Switch
                id="bonus-override-enabled"
                checked={bonusOverrideEnabled}
                onCheckedChange={setBonusOverrideEnabled}
                disabled={!isAdmin}
                aria-label="Bật quy tắc cộng điểm tùy chỉnh"
              />
            </div>
            {bonusOverrideEnabled && (
              <div className="space-y-3 pl-3 border-l-2">
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="apply-area-bonus"
                    checked={applyAreaBonus}
                    onCheckedChange={(v) => setApplyAreaBonus(v === true)}
                    disabled={!isAdmin}
                    aria-label="Cộng điểm khu vực"
                  />
                  <Label
                    htmlFor="apply-area-bonus"
                    className="text-sm cursor-pointer"
                  >
                    Cộng điểm khu vực (KV1 / KV2_NT / KV2 / KV3)
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="apply-subject-bonus"
                    checked={applySubjectBonus}
                    onCheckedChange={(v) => setApplySubjectBonus(v === true)}
                    disabled={!isAdmin}
                    aria-label="Cộng điểm môn ưu tiên"
                  />
                  <Label
                    htmlFor="apply-subject-bonus"
                    className="text-sm cursor-pointer"
                  >
                    Cộng điểm đối tượng ưu tiên (mã 01..07)
                  </Label>
                </div>
                <div className="space-y-1">
                  <Label
                    htmlFor="max-total-bonus"
                    className="text-sm font-medium"
                  >
                    Trần tổng cộng điểm (0..10)
                  </Label>
                  <Input
                    id="max-total-bonus"
                    type="number"
                    value={maxTotalBonusInput}
                    onChange={(e) => setMaxTotalBonusInput(e.target.value)}
                    min={0}
                    max={10}
                    step={0.25}
                    placeholder="Để trống = không giới hạn"
                    disabled={!isAdmin}
                  />
                </div>
              </div>
            )}
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
