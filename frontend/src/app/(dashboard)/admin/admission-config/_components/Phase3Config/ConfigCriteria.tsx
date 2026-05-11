"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Loader2, ArrowRight, ArrowLeft, Search, X, Save } from "lucide-react";
import { toast } from "sonner";

import { useUpdateCriteria } from "@/hooks/admissions/useAdmissionPaths";
import { useSubjectGroups } from "@/hooks/admissions/useMasterData";
import { AdmissionPathResponse } from "@/lib/zod/admission-path";
import type { SubjectGroup } from "../shared/types";
import type { PydanticValidationError } from "@/types/api.types";

interface ConfigCriteriaProps {
  path: AdmissionPathResponse;
  onNext: () => void;
  onBack: () => void;
  /** Khi true: render footer "Đóng" + "Lưu tiêu chí" (drawer mode) thay vì
   * "Quay lại" + "Lưu & Tiếp tục" (wizard mode). */
  embedded?: boolean;
}

export function ConfigCriteria({ path, onNext, onBack, embedded = false }: ConfigCriteriaProps) {
  const { data: subjectGroups = [], isLoading: loadingGroups } = useSubjectGroups();
  const updateMutation = useUpdateCriteria();

  // Form State
  const [minGpa, setMinGpa] = useState<string>(path.criteria?.min_gpa?.toString() || "");
  const [minScore, setMinScore] = useState<string>(path.criteria?.min_score?.toString() || "");
  const [minSubjectScore, setMinSubjectScore] = useState<string>(path.criteria?.min_subject_score?.toString() || "");
  const [maxScore, setMaxScore] = useState<string>(path.criteria?.max_possible_score?.toString() || "");
  const [conditions, setConditions] = useState<string>(path.criteria?.conditions || "");
  const [requiredSubjectCount, setRequiredSubjectCount] = useState<string>(path.criteria?.required_subject_count?.toString() || "");
  
  // Hotfix: parity với Zod admissionCriteriaCreateSchema sau CHECKPOINT 7
  // (enum đã đổi "avg" → ["sum", "average", "weighted"] match BE).
  const [scoringMethod, setScoringMethod] = useState<"sum" | "average" | "weighted">(
    (path.criteria?.scoring_method as "sum" | "average" | "weighted") || "sum",
  );
  const [selectionMode, setSelectionMode] = useState<"fixed" | "best_n" | "any_n">((path.criteria?.subject_selection_mode as "fixed" | "best_n" | "any_n") || "fixed");
  const [selectedGroups, setSelectedGroups] = useState<number[]>(path.criteria?.subject_groups?.map(g => g.id) || []);
  
  // Validity State
  const [policyVersion, setPolicyVersion] = useState<string>(path.criteria?.policy_version || "2025.1");
  const [effectiveFrom, setEffectiveFrom] = useState<string>(path.criteria?.effective_from || "");
  const [effectiveTo, setEffectiveTo] = useState<string>(path.criteria?.effective_to || "");

  // Search state for filtering subject groups
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Pass 2 hard-review FM-4: debounce search input để tránh filter 281
  // subject groups + re-render checkbox grid mỗi keystroke. 200ms = ngắn
  // đủ feel responsive, đủ skip rapid typing.
  const [debouncedSearch, setDebouncedSearch] = useState<string>("");
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(searchQuery), 200);
    return () => clearTimeout(handle);
  }, [searchQuery]);

  // Sync form state when path data loads
  const currentPathId = path.id;

  // REMOVED useEffect sync - relying on key-based remount from parent (PathWizard)
  // to re-initialize these states when path/criteria changes.

  // Handlers

  // Filter subject groups based on debounced search query.
  // Wrap trong useMemo để re-compute chỉ khi groups hoặc query thay đổi
  // (không re-compute trên mỗi state change khác trong component).
  const filteredGroups = useMemo(() => {
    if (!Array.isArray(subjectGroups)) return [] as SubjectGroup[];
    if (!debouncedSearch) return subjectGroups;
    const query = debouncedSearch.toLowerCase();
    return subjectGroups.filter((group: SubjectGroup) =>
      (group.code?.toLowerCase() || "").includes(query) ||
      (group.name?.toLowerCase() || "").includes(query)
    );
  }, [subjectGroups, debouncedSearch]);

  // Get selected group details for chip display
  const selectedGroupsDetails = subjectGroups.filter((group: SubjectGroup) =>
    selectedGroups.includes(group.id)
  );

  // Handlers
  const handleGroupToggle = (groupId: number) => {
    setSelectedGroups(prev =>
      prev.includes(groupId)
        ? prev.filter(id => id !== groupId)
        : [...prev, groupId]
    );
  };

  const handleRemoveGroup = (groupId: number) => {
    setSelectedGroups(prev => prev.filter(id => id !== groupId));
  };

  const handleSave = async () => {
    // Validation
    if (selectedGroups.length === 0) {
      toast.warning("Vui lòng chọn ít nhất một tổ hợp môn");
      return;
    }

    if (effectiveFrom && effectiveTo) {
      // Parse ISO date string ('YYYY-MM-DD') to Date trước khi compare —
      // string compare lexical sai cho format không zero-pad consistent.
      const fromTs = Date.parse(effectiveFrom);
      const toTs = Date.parse(effectiveTo);
      if (!isNaN(fromTs) && !isNaN(toTs) && fromTs > toTs) {
        toast.warning("Ngày bắt đầu hiệu lực không được lớn hơn ngày kết thúc");
        return;
      }
    }

    try {
      // Helper to safely parse float and avoid NaN
      const safeParseFloat = (value: string): number | null => {
        if (!value || value.trim() === "") return null;
        const parsed = parseFloat(value.trim());
        return isNaN(parsed) ? null : parsed;
      };

      const safeParseInt = (value: string): number | null => {
        if (!value || value.trim() === "") return null;
        const parsed = parseInt(value.trim());
        return isNaN(parsed) ? null : parsed;
      };

      // 1. Validate Selection Mode & N
      if (selectionMode === "best_n" || selectionMode === "any_n") {
        const n = safeParseInt(requiredSubjectCount);
        if (!n || n <= 0) {
           toast.warning("Vui lòng nhập số môn bắt buộc (N) lớn hơn 0");
           return;
        }

        // Calculate total unique subjects from selected groups
        const uniqueSubjects = new Set<string>();
        selectedGroupsDetails.forEach((g: SubjectGroup) => {
            g.subjects?.forEach(s => uniqueSubjects.add(s.code));
        });
        
        if (n > uniqueSubjects.size) {
            toast.warning(`Số môn yêu cầu (${n}) không được lớn hơn tổng số môn có trong các tổ hợp đã chọn (${uniqueSubjects.size} môn)`);
            return;
        }
      }

      // 2. Validate Max Score vs Min Score
      const minS = safeParseFloat(minScore);
      const maxS = safeParseFloat(maxScore);

      if (maxS !== null && minS !== null && maxS < minS) {
          toast.warning(`Điểm tối đa (${maxS}) không được nhỏ hơn điểm chuẩn (${minS})`);
          return;
      }
      
      // 3. Score Logic Warning
      if (selectionMode === "best_n" && maxS !== null) {
         const n = safeParseInt(requiredSubjectCount);
         if (n && (maxS < n * 10)) {
             // Just a warning, not a block, as some scales might be different
             // But usually Max = N * 10
             // toast.info(`Lưu ý: Với ${n} môn, điểm tối đa thường là ${n * 10}`);
         }
      }

      // Prepare data with proper type conversion
      const payload = {
        min_gpa: safeParseFloat(minGpa),
        min_score: safeParseFloat(minScore),
        min_subject_score: safeParseFloat(minSubjectScore),
        max_possible_score: safeParseFloat(maxScore),
        conditions: conditions && conditions.trim() !== "" ? conditions.trim() : null,
        required_subject_count: safeParseInt(requiredSubjectCount),
        scoring_method: scoringMethod,
        subject_selection_mode: selectionMode,
        subject_groups: selectedGroups,
        policy_version: policyVersion,
        effective_from: effectiveFrom || null,
        effective_to: effectiveTo || null,
      };

      await updateMutation.mutateAsync({
        pathId: path.id,
        data: payload
      });
      toast.success("Đã lưu tiêu chí xét tuyển thành công");
      // Move to next step after successful save
      onNext();
    } catch (error: unknown) {
      const apiError = error as { response?: { data?: { detail?: unknown } } };
      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.error("ConfigCriteria save error:", error, apiError?.response?.data);
      }

      // Extract validation error details
      const errorDetail = apiError?.response?.data?.detail;
      let errorMessage = "Lưu thất bại. Vui lòng kiểm tra lại.";

      if (Array.isArray(errorDetail)) {
        // Pydantic validation errors
        errorMessage = errorDetail.map((e: PydanticValidationError) => `${e.loc?.join('.')}: ${e.msg}`).join(", ");
      } else if (typeof errorDetail === "string") {
        errorMessage = errorDetail;
      }

      toast.error(errorMessage);
    }
  };

  const isSaving = updateMutation.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cấu hình Tiêu chí Xét tuyển</CardTitle>
        <CardDescription>
          Thiết lập điểm sàn, cách tính điểm và tổ hợp môn
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        
        {/* Row 1: Thresholds */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label htmlFor="minGpa">Điểm sàn học bạ (Min GPA)</Label>
            <Input 
              id="minGpa" 
              type="number" 
              step="0.1" 
              placeholder="Vd: 6.0"
              value={minGpa}
              onChange={(e) => setMinGpa(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Thang điểm 10</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="minScore">Điểm chuẩn (Min Score)</Label>
            <Input 
              id="minScore" 
              type="number" 
              step="0.1" 
              placeholder="Vd: 18.0"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Tổng điểm xét tuyển</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="minSubjectScore">Điểm liệt (Min Subject)</Label>
            <Input 
              id="minSubjectScore" 
              type="number" 
              step="0.1" 
              placeholder="Vd: 1.0"
              value={minSubjectScore}
              onChange={(e) => setMinSubjectScore(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Điểm tối thiểu mỗi môn</p>
          </div>
        </div>

        {/* Row 2: Method Config */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label>Cách tính điểm</Label>
            <Select
              value={scoringMethod}
              onValueChange={(val: "sum" | "average" | "weighted") =>
                setScoringMethod(val)
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sum">Tổng điểm</SelectItem>
                <SelectItem value="average">Điểm trung bình</SelectItem>
                <SelectItem value="weighted">Có hệ số (weighted)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Chế độ chọn môn</Label>
            <div className="flex gap-3">

              <div className="flex-1">
                <Select 
                  value={selectionMode} 
                  onValueChange={(val: "fixed" | "best_n" | "any_n") => setSelectionMode(val)}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="fixed">Cố định (Fixed)</SelectItem>
                    <SelectItem value="best_n">Linh hoạt (Best N)</SelectItem>
                    <SelectItem value="any_n">Tùy chọn (Any N)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              
              <div className="w-24">
                <Input 
                   id="requiredSubjectCount"
                   type="number" 
                   step="1"
                   min="1"
                   max="10"
                   placeholder="N"
                   value={requiredSubjectCount}
                   onChange={(e) => setRequiredSubjectCount(e.target.value)}
                   className="text-center"
                   title="Số môn bắt buộc (N)"
                />
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {selectionMode === "fixed" ? "Chọn đúng N môn trong tổ hợp" : `Lấy ${requiredSubjectCount || "N"} môn cao nhất`}
            </p>
          </div>
           <div className="space-y-2">
            <Label htmlFor="maxScore">Thang điểm tối đa</Label>
             <Input 
              id="maxScore" 
              type="number" 
              step="1" 
              placeholder="Vd: 30"
              value={maxScore}
              onChange={(e) => setMaxScore(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">Vd: 30, 1200</p>
          </div>
        </div>

        {/* Validity Config */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
           <div className="space-y-2">
            <Label htmlFor="policyVersion">Phiên bản Quy chế</Label>
             <Input 
              id="policyVersion" 
              placeholder="Vd: 2025.1"
              value={policyVersion}
              onChange={(e) => setPolicyVersion(e.target.value)}
            />
          </div>
           <div className="space-y-2">
            <Label htmlFor="effectiveFrom">Hiệu lực từ ngày</Label>
             <Input 
              id="effectiveFrom" 
              type="date"
              value={effectiveFrom}
              onChange={(e) => setEffectiveFrom(e.target.value)}
            />
          </div>
           <div className="space-y-2">
            <Label htmlFor="effectiveTo">Đến ngày (Tùy chọn)</Label>
             <Input 
              id="effectiveTo" 
              type="date"
              value={effectiveTo}
              onChange={(e) => setEffectiveTo(e.target.value)}
            />
          </div>
        </div>

        {/* Conditions */}
         <div className="space-y-2">
          <Label htmlFor="conditions">Điều kiện phụ / Ghi chú</Label>
          <Textarea 
            id="conditions" 
            placeholder="Nhập ghi chú hoặc điều kiện phụ (nếu có)..."
            value={conditions}
            onChange={(e) => setConditions(e.target.value)}
            rows={3}
          />
        </div>

        {/* Subject Groups Selection */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label>Tổ hợp môn được phép</Label>
            <span className="text-xs text-muted-foreground">
              Đã chọn: {selectedGroups.length} tổ hợp
            </span>
          </div>

          {/* Selected Groups as Chips */}
          {selectedGroupsDetails.length > 0 && (
            <div className="flex flex-wrap gap-2 p-3 bg-info-50 border border-info-200 rounded-md">
              {selectedGroupsDetails.map((group: SubjectGroup) => (
                <Badge
                  key={group.id}
                  variant="secondary"
                  className="flex items-center gap-1 px-2 py-1 bg-info-100 text-info-800 hover:bg-info-200"
                >
                  <span className="font-medium">{group.code}</span>
                  <span className="text-xs opacity-75">({group.name})</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveGroup(group.id)}
                    className="ml-1 hover:bg-info-300 rounded-full p-0.5"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}

          {/* Search Input */}
          <div className="relative">
            <Search
              className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none"
              aria-hidden="true"
            />
            <Input
              placeholder="Tìm kiếm tổ hợp môn (mã hoặc tên môn)…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              className={searchQuery ? "pl-9 pr-9" : "pl-9"}
              aria-label="Tìm kiếm tổ hợp môn"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                aria-label="Xoá từ khoá tìm kiếm"
                className="absolute right-2 top-1/2 transform -translate-y-1/2 hover:bg-muted rounded-full p-1"
              >
                <X className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              </button>
            )}
          </div>

          {/* Scrollable List */}
          <div className="border rounded-md">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 p-4 max-h-60 overflow-y-auto">
              {loadingGroups ? (
                <div className="col-span-3 flex justify-center py-4">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : filteredGroups.length === 0 ? (
                <div className="col-span-3 text-center py-4 text-muted-foreground text-sm">
                  Không tìm thấy tổ hợp môn nào phù hợp với &quot;{searchQuery}&quot;
                </div>
              ) : (
                filteredGroups.map((group: SubjectGroup) => (
                  <div key={group.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={`group-${group.id}`}
                      checked={selectedGroups.includes(group.id)}
                      onCheckedChange={() => handleGroupToggle(group.id)}
                    />
                    <Label
                      htmlFor={`group-${group.id}`}
                      className="text-sm font-normal cursor-pointer"
                    >
                      {group.code} <span className="text-xs text-muted-foreground">({group.name})</span>
                    </Label>
                  </div>
                ))
              )}
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            Chọn các tổ hợp môn thí sinh có thể dùng để xét tuyển.
          </p>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-4 border-t">
          <Button variant="outline" onClick={onBack} disabled={isSaving}>
            {!embedded && <ArrowLeft className="h-4 w-4 mr-2" aria-hidden="true" />}
            {embedded ? "Đóng" : "Quay lại"}
          </Button>
          <Button onClick={handleSave} disabled={isSaving} aria-busy={isSaving}>
            {isSaving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" aria-hidden="true" />
            ) : (
              <Save className="h-4 w-4 mr-2" aria-hidden="true" />
            )}
            {embedded ? "Lưu tiêu chí" : "Lưu & Tiếp tục"}
            {!embedded && <ArrowRight className="h-4 w-4 ml-2" aria-hidden="true" />}
          </Button>
        </div>

      </CardContent>
    </Card>
  );
}
