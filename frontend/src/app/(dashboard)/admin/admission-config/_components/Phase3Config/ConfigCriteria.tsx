"use client";

import { useState, useEffect } from "react";
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

interface ConfigCriteriaProps {
  path: AdmissionPathResponse;
  onNext: () => void;
  onBack: () => void;
}

export function ConfigCriteria({ path, onNext, onBack }: ConfigCriteriaProps) {
  const { data: subjectGroups = [], isLoading: loadingGroups } = useSubjectGroups();
  const updateMutation = useUpdateCriteria();

  // Form State
  const [minGpa, setMinGpa] = useState<string>("");
  const [minScore, setMinScore] = useState<string>("");
  const [minSubjectScore, setMinSubjectScore] = useState<string>("");
  const [maxScore, setMaxScore] = useState<string>("");
  const [conditions, setConditions] = useState<string>("");
  const [requiredSubjectCount, setRequiredSubjectCount] = useState<string>("");
  
  const [scoringMethod, setScoringMethod] = useState<"sum" | "avg">("sum");
  const [selectionMode, setSelectionMode] = useState<"fixed" | "dynamic">("fixed");
  const [selectedGroups, setSelectedGroups] = useState<number[]>([]);
  
  // Validity State
  const [policyVersion, setPolicyVersion] = useState<string>("2025.1");
  const [effectiveFrom, setEffectiveFrom] = useState<string>("");
  const [effectiveTo, setEffectiveTo] = useState<string>("");

  // Search state for filtering subject groups
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Initialize from existing criteria
  useEffect(() => {
    if (path.criteria) {
      setMinGpa(path.criteria.min_gpa?.toString() || "");
      setMinScore(path.criteria.min_score?.toString() || "");
      setMinSubjectScore(path.criteria.min_subject_score?.toString() || "");
      setMaxScore(path.criteria.max_possible_score?.toString() || "");
      setConditions(path.criteria.conditions || "");
      setRequiredSubjectCount(path.criteria.required_subject_count?.toString() || "");
      
      setScoringMethod((path.criteria.scoring_method as "sum" | "avg") || "sum");
      setSelectionMode((path.criteria.subject_selection_mode as "fixed" | "dynamic") || "fixed");
      
      setPolicyVersion(path.criteria.policy_version || "2025.1");
      setEffectiveFrom(path.criteria.effective_from || "");
      setEffectiveTo(path.criteria.effective_to || "");

      // Map nested groups to IDs
      const groupIds = path.criteria.subject_groups.map(g => g.id);
      setSelectedGroups(groupIds);
    }
  }, [path.criteria]);

  // Filter subject groups based on search query
  // Filter subject groups based on search query
  const filteredGroups = Array.isArray(subjectGroups) 
    ? subjectGroups.filter((group: any) => {
        if (!searchQuery) return true;
        const query = searchQuery.toLowerCase();
        return (
          (group.code?.toLowerCase() || "").includes(query) ||
          (group.name?.toLowerCase() || "").includes(query)
        );
      })
    : [];

  // Get selected group details for chip display
  const selectedGroupsDetails = subjectGroups.filter((group: any) =>
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

    try {
      // Helper to safely parse float and avoid NaN
      const safeParseFloat = (value: string): number | null => {
        if (!value || value.trim() === "") return null;
        const parsed = parseFloat(value.trim());
        return isNaN(parsed) ? null : parsed;
      };

      // Helper to safely parse int and avoid NaN
      const safeParseInt = (value: string): number | null => {
        if (!value || value.trim() === "") return null;
        const parsed = parseInt(value.trim());
        return isNaN(parsed) ? null : parsed;
      };

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

      console.log("Sending criteria payload:", payload);

      await updateMutation.mutateAsync({
        pathId: path.id,
        data: payload
      });
      toast.success("Đã lưu tiêu chí xét tuyển thành công");
      // Move to next step after successful save
      onNext();
    } catch (error: any) {
      console.error("Failed to save criteria:", error);
      console.error("Error response:", error?.response?.data);

      // Extract validation error details
      const errorDetail = error?.response?.data?.detail;
      let errorMessage = "Lưu thất bại. Vui lòng kiểm tra lại.";

      if (Array.isArray(errorDetail)) {
        // Pydantic validation errors
        errorMessage = errorDetail.map((e: any) => `${e.loc?.join('.')}: ${e.msg}`).join(", ");
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
              onValueChange={(val: "sum" | "avg") => setScoringMethod(val)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sum">Tổng điểm (3 môn)</SelectItem>
                <SelectItem value="avg">Điểm trung bình</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Chế độ chọn môn</Label>
            <Select 
              value={selectionMode} 
              onValueChange={(val: "fixed" | "dynamic") => setSelectionMode(val)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">Cố định (Theo tổ hợp)</SelectItem>
                <SelectItem value="dynamic">Linh hoạt (Best N)</SelectItem>
              </SelectContent>
            </Select>
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
            <div className="flex flex-wrap gap-2 p-3 bg-blue-50 border border-blue-200 rounded-md">
              {selectedGroupsDetails.map((group: any) => (
                <Badge
                  key={group.id}
                  variant="secondary"
                  className="flex items-center gap-1 px-2 py-1 bg-blue-100 text-blue-800 hover:bg-blue-200"
                >
                  <span className="font-medium">{group.code}</span>
                  <span className="text-xs opacity-75">({group.name})</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveGroup(group.id)}
                    className="ml-1 hover:bg-blue-300 rounded-full p-0.5"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}

          {/* Search Input */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Tìm kiếm tổ hợp môn (mã hoặc tên môn)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-3 top-1/2 transform -translate-y-1/2 hover:bg-gray-100 rounded-full p-1"
              >
                <X className="h-4 w-4 text-muted-foreground" />
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
                  Không tìm thấy tổ hợp môn nào phù hợp với "{searchQuery}"
                </div>
              ) : (
                filteredGroups.map((group: any) => (
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
        <div className="flex justify-between pt-4">
          <Button variant="outline" onClick={onBack} disabled={isSaving}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Quay lại
          </Button>
          <Button onClick={handleSave} disabled={isSaving}>
            {isSaving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Lưu & Tiếp tục
            <ArrowRight className="h-4 w-4 ml-2" />
          </Button>
        </div>

      </CardContent>
    </Card>
  );
}
