/**
 * ContextSelector Component
 *
 * Phase 3: Context Selection
 * Full-screen interface for selecting the context (Year + Major + Offering)
 * before configuring admission paths
 */

"use client";

import { useState, useMemo } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Calendar, GraduationCap, BookOpen, ArrowRight, AlertCircle, Check } from "lucide-react";
import { useAcademicYears } from "@/hooks/admissions/useAdmissionPaths";
import { useMajorPrograms } from "@/hooks/admissions/useProgramData";
import { useProgramOfferings, useOfferingAcademicInfos } from "@/hooks/admissions/useProgramData";
import type {
  SelectionContext,
  MajorProgram,
  ProgramOffering,
  OfferingAcademicInfo
} from "../shared/types";

// ============================================
// TYPES
// ============================================

interface ContextSelectorProps {
  onContextSelected: (context: SelectionContext) => void;
}

// ============================================
// COMPONENT
// ============================================

export function ContextSelector({ onContextSelected }: ContextSelectorProps) {
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [selectedMajorId, setSelectedMajorId] = useState<number | null>(null);
  const [selectedOfferingId, setSelectedOfferingId] = useState<number | null>(null);
  const [selectedAcademicInfoId, setSelectedAcademicInfoId] = useState<number | null>(null);

  // Fetch data
  const { data: yearsData, isLoading: loadingYears } = useAcademicYears();
  const { data: majors = [], isLoading: loadingMajors } = useMajorPrograms();
  const { data: offerings = [], isLoading: loadingOfferings } = useProgramOfferings();
  const { data: academicInfos = [], isLoading: loadingAcademicInfos } = useOfferingAcademicInfos();

  // Filter majors to only those with offerings that have academic info in selected year
  const filteredMajors = useMemo(() => {
    if (!selectedYear) return majors;
    const offeringIdsWithYear = new Set(
      academicInfos.filter((ai: OfferingAcademicInfo) => ai.academic_year === selectedYear).map((ai: OfferingAcademicInfo) => ai.offering_id)
    );
    const majorIdsWithYear = new Set(
      offerings.filter((o: ProgramOffering) => offeringIdsWithYear.has(o.id)).map((o: ProgramOffering) => o.program_id)
    );
    return majors.filter((m: MajorProgram) => majorIdsWithYear.has(m.id));
  }, [majors, offerings, academicInfos, selectedYear]);

  // Filter offerings by selected major AND selected year (only show offerings with academic info in that year)
  const filteredOfferings = useMemo(() => {
    if (!selectedMajorId) return [];
    const byMajor = offerings.filter((o: ProgramOffering) => o.program_id === selectedMajorId);
    if (!selectedYear) return byMajor;
    const offeringIdsWithYear = new Set(
      academicInfos.filter((ai: OfferingAcademicInfo) => ai.academic_year === selectedYear).map((ai: OfferingAcademicInfo) => ai.offering_id)
    );
    return byMajor.filter((o: ProgramOffering) => offeringIdsWithYear.has(o.id));
  }, [offerings, academicInfos, selectedMajorId, selectedYear]);

  // Filter academic infos by selected offering and year
  const filteredAcademicInfos = useMemo(() => {
    if (!selectedOfferingId || !selectedYear) return [];
    return academicInfos.filter(
      (info: OfferingAcademicInfo) =>
        info.offering_id === selectedOfferingId && info.academic_year === selectedYear
    );
  }, [academicInfos, selectedOfferingId, selectedYear]);

  // Get current academic info for display
  const currentAcademicInfo = useMemo(() => {
    if (!selectedAcademicInfoId) return null;
    return filteredAcademicInfos.find((info: OfferingAcademicInfo) => info.id === selectedAcademicInfoId) || null;
  }, [filteredAcademicInfos, selectedAcademicInfoId]);

  // Check if all selections are valid
  const isComplete =
    selectedYear !== null &&
    selectedMajorId !== null &&
    selectedOfferingId !== null &&
    selectedAcademicInfoId !== null;

  // Handle year change
  const handleYearChange = (value: string) => {
    const year = parseInt(value);
    setSelectedYear(year);
    // Reset dependent selections
    setSelectedMajorId(null);
    setSelectedOfferingId(null);
    setSelectedAcademicInfoId(null);
  };

  // Handle major change
  const handleMajorChange = (value: string) => {
    const majorId = parseInt(value);
    setSelectedMajorId(majorId);
    // Reset dependent selections
    setSelectedOfferingId(null);
    setSelectedAcademicInfoId(null);
  };

  // Handle offering change
  const handleOfferingChange = (value: string) => {
    const offeringId = parseInt(value);
    setSelectedOfferingId(offeringId);
    // Reset academic info - it will be auto-selected if there's only one match
    setSelectedAcademicInfoId(null);

    // Auto-select if there's exactly one academic info for this offering/year combination
    const matchingInfos = academicInfos.filter(
      (info: OfferingAcademicInfo) =>
        info.offering_id === offeringId && info.academic_year === selectedYear
    );
    if (matchingInfos.length === 1) {
      setSelectedAcademicInfoId(matchingInfos[0].id);
    }
  };

  // Handle continue button
  const handleContinue = () => {
    if (!isComplete) return;

    onContextSelected({
      academicYear: selectedYear!,
      majorProgramId: selectedMajorId!,
      offeringId: selectedOfferingId!,
      academicInfoId: selectedAcademicInfoId!,
    });
  };

  return (
    <div className="flex items-center justify-center min-h-[80vh] p-6">
      <Card className="max-w-3xl w-full">
        <CardHeader>
          <CardTitle className="text-2xl">Chọn Ngữ cảnh Cấu hình</CardTitle>
          <CardDescription>
            Chọn năm học và chương trình tuyển sinh để cấu hình đợt tuyển sinh
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-6">
          {/* Step 1: Academic Year */}
          <div className="space-y-2">

            <Label htmlFor="year" className="text-base font-semibold flex items-center gap-2">
              <Calendar className="h-4 w-4" />
              Bước 1: Chọn Năm học
            </Label>
            <Select value={selectedYear?.toString() || ""} onValueChange={handleYearChange}>
              <SelectTrigger id="year" className="h-12">
                <SelectValue placeholder="Chọn năm học" />
              </SelectTrigger>
              <SelectContent>
                {loadingYears ? (
                  <div className="p-2 text-sm text-muted-foreground">Loading years...</div>
                ) : yearsData?.years && yearsData.years.length > 0 ? (
                  yearsData.years.map((year: number) => (
                    <SelectItem key={year} value={year.toString()}>
                      {year} {year === yearsData.current_year && "(Năm hiện tại)"}
                    </SelectItem>
                  ))
                ) : (
                  <div className="p-2 text-sm text-muted-foreground">
                    Không có năm học nào
                  </div>
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Step 2: Major Program */}
          <div className="space-y-2">

            <Label htmlFor="major" className="text-base font-semibold flex items-center gap-2">
              <GraduationCap className="h-4 w-4" />
              Bước 2: Chọn Ngành đào tạo
            </Label>
            <Select
              value={selectedMajorId?.toString() || ""}
              onValueChange={handleMajorChange}
              disabled={!selectedYear}
            >
              <SelectTrigger id="major" className="h-12">
                <SelectValue placeholder={selectedYear ? "Chọn ngành đào tạo" : "Vui lòng chọn năm trước"} />
              </SelectTrigger>
              <SelectContent>
                {loadingMajors ? (
                  <div className="p-2 text-sm text-muted-foreground">Đang tải ngành...</div>
                ) : filteredMajors.length > 0 ? (
                  filteredMajors.map((major: MajorProgram) => (
                    <SelectItem key={major.id} value={major.id.toString()}>
                      {major.name}
                      <span className="text-muted-foreground ml-2">({major.code})</span>
                    </SelectItem>
                  ))
                ) : (
                  <div className="p-2 text-sm text-muted-foreground">
                    Không có ngành đào tạo nào
                  </div>
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Step 3: Program Offering */}
          <div className="space-y-2">

            <Label htmlFor="offering" className="text-base font-semibold flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              Bước 3: Chọn Chương trình tuyển sinh
            </Label>
            <Select
              value={selectedOfferingId?.toString() || ""}
              onValueChange={handleOfferingChange}
              disabled={!selectedMajorId}
            >
              <SelectTrigger id="offering" className="h-12">
                <SelectValue placeholder={selectedMajorId ? "Chọn chương trình tuyển sinh" : "Vui lòng chọn ngành trước"} />
              </SelectTrigger>
              <SelectContent>
                {loadingOfferings ? (
                  <div className="p-2 text-sm text-muted-foreground">Đang tải chương trình...</div>
                ) : filteredOfferings.length > 0 ? (
                  filteredOfferings.map((offering: ProgramOffering) => {
                    const relevantInfo = offering.academic_info_history?.find(
                      (info) => info.academic_year === selectedYear
                    );
                    const isConfigured = relevantInfo?.admission_status === 'CONFIGURED';

                    return (
                      <SelectItem key={offering.id} value={offering.id.toString()}>
                        <div className="flex items-center justify-between w-full gap-2 min-w-[300px]">
                          <span>
                            {offering.program?.name || `Program #${offering.program_id}`} - {offering.offering_type}
                          </span>
                          {isConfigured && <Check className="h-4 w-4 text-success-500" />}
                        </div>
                      </SelectItem>
                    );
                  })
                ) : (
                  <div className="p-2 text-sm text-muted-foreground">
                    Không có chương trình nào cho ngành này
                  </div>
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Academic Info Status */}
          {selectedOfferingId && selectedYear && (
            <div className="bg-muted rounded-lg p-4">
              {loadingAcademicInfos ? (
                <p className="text-sm text-muted-foreground">Đang kiểm tra thông tin năm học...</p>
              ) : filteredAcademicInfos.length === 0 ? (
                <div className="flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
                  <div>
                    <p className="font-medium text-destructive">Không tìm thấy Thông tin Tuyển sinh chi tiết</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      Chưa có cấu hình chi tiết cho chương trình này trong năm {selectedYear}.
                      Vui lòng tạo ở Bước 2.3 trước.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3">
                  <Calendar className="h-5 w-5 text-success-600 mt-0.5" />
                  <div>
                    <p className="font-medium">Đã tìm thấy Thông tin</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      Chỉ tiêu: {currentAcademicInfo?.annual_admission_quota || "Chưa thiết lập"} sinh viên
                    </p>
                    {currentAcademicInfo?.tuition_fee_per_year && (
                      <p className="text-sm text-muted-foreground">
                        Học phí: {new Intl.NumberFormat("vi-VN", {
                          style: "currency",
                          currency: "VND",
                        }).format(currentAcademicInfo.tuition_fee_per_year)}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Continue Button */}
          <div className="flex justify-end pt-4">
            <Button
              size="lg"
              onClick={handleContinue}
              disabled={!isComplete}
              className="gap-2"
            >
              Tiếp tục đến Cấu hình Đợt tuyển sinh
              <ArrowRight className="h-5 w-5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
