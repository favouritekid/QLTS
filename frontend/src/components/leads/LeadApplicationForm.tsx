// src/components/leads/LeadApplicationForm.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Loader2, Save } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

import { useUpdateApplication } from "@/hooks/useApplication";
import { useMajorPrograms, useOfferingAcademicInfoList } from "@/hooks/useOrganization";
import { DocumentChecklist } from "./DocumentChecklist";
import type { Lead, Application, ApplicationUpdate, ChecklistItem } from "@/types/lead.types";
import type { MajorProgram, ProgramOffering, AdmissionCriterion } from "@/types/organization.types";

// Validation schema
const applicationSchema = z.object({
  major_program_id: z.number().nullable(),
  program_offering_id: z.number().nullable(),
  criterion_id: z.string().nullable(),
  status: z.enum(["pending", "missing_documents", "completed", "passed", "failed"]),
  documents: z.object({
    scores: z.record(z.string(), z.number().nullable()).nullable().optional(),
    checklist: z.array(
      z.object({
        code: z.string(),
        label: z.string(),
        status: z.enum(["missing", "submitted", "verified", "rejected"]),
        submission_type: z.enum(["N/A", "photocopy", "notarized", "original", "incomplete"]),
        notes: z.string(),
      })
    ).nullable().optional(),
  }).nullable(),
});

type ApplicationFormValues = z.infer<typeof applicationSchema>;

interface LeadApplicationFormProps {
  lead: Lead;
  application: Application;
}

export function LeadApplicationForm({ lead, application }: LeadApplicationFormProps) {
  const updateApplication = useUpdateApplication(application.id);

  // Fetch major programs for the unit
  const { data: majorPrograms = [], isLoading: majorProgramsLoading } = useMajorPrograms(lead.unit_id);

  // Initialize form
  const form = useForm<ApplicationFormValues>({
    resolver: zodResolver(applicationSchema),
    defaultValues: {
      major_program_id: application.major_program_id,
      program_offering_id: application.program_offering_id,
      criterion_id: application.criterion_id,
      status: application.status,
      documents: application.documents || { scores: null, checklist: null },
    },
  });

  // Watch form values for cascade logic
  const selectedMajorProgramId = form.watch("major_program_id");
  const selectedOfferingId = form.watch("program_offering_id");
  const selectedCriterionId = form.watch("criterion_id");

  // Find selected objects
  const selectedMajorProgram = majorPrograms.find((p) => p.id === selectedMajorProgramId);
  const selectedOffering = selectedMajorProgram?.offerings?.find(
    (o) => o.id === selectedOfferingId
  );

  // Fetch academic info for selected offering
  const {
    data: academicInfoList = [],
    isLoading: academicInfoLoading,
  } = useOfferingAcademicInfoList(selectedOfferingId || 0, true);

  // Get first published academic info
  const academicInfo = academicInfoList.length > 0 ? academicInfoList[0] : null;
  const admissionCriteria = academicInfo?.admission_criteria || [];

  // Find selected criterion
  const selectedCriterion = admissionCriteria.find((c) => c.id === selectedCriterionId);

  // Handle form submission
  const onSubmit = async (data: ApplicationFormValues) => {
    const payload: ApplicationUpdate = {
      major_program_id: data.major_program_id,
      program_offering_id: data.program_offering_id,
      criterion_id: data.criterion_id,
      status: data.status,
      documents: data.documents ? {
        scores: data.documents.scores ?? null,
        checklist: data.documents.checklist ?? null,
      } : null,
    };

    updateApplication.mutate(payload);
  };

  return (
    <div className="space-y-6">
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
          {/* Card 1: Ngành học Ứng tuyển (Dropdown Động 3 Cấp) */}
          <Card>
            <CardHeader>
              <CardTitle>Ngành học Ứng tuyển</CardTitle>
              <CardDescription>
                Chọn ngành đào tạo, loại hình và phương thức xét tuyển
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Dropdown 1: Major Program */}
              <FormField
                control={form.control}
                name="major_program_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Ngành đào tạo *</FormLabel>
                    <Select
                      onValueChange={(value) => {
                        const numValue = value ? Number(value) : null;
                        field.onChange(numValue);
                        // Reset cascade
                        form.setValue("program_offering_id", null);
                        form.setValue("criterion_id", null);
                        form.setValue("documents.scores", null);
                        form.setValue("documents.checklist", null);
                      }}
                      value={field.value?.toString() || ""}
                      disabled={majorProgramsLoading}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn ngành đào tạo" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {majorPrograms.length === 0 ? (
                          <div className="p-2 text-sm text-muted-foreground">
                            Không có ngành đào tạo
                          </div>
                        ) : (
                          majorPrograms.map((program) => (
                            <SelectItem key={program.id} value={program.id.toString()}>
                              {program.name} ({program.code}) - {program.degree_level}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Chọn chương trình đào tạo mà thí sinh muốn ứng tuyển
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Dropdown 2: Program Offering */}
              <FormField
                control={form.control}
                name="program_offering_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Loại hình đào tạo *</FormLabel>
                    <Select
                      onValueChange={(value) => {
                        const numValue = value ? Number(value) : null;
                        field.onChange(numValue);
                        // Reset cascade
                        form.setValue("criterion_id", null);
                        form.setValue("documents.scores", null);
                        form.setValue("documents.checklist", null);
                      }}
                      value={field.value?.toString() || ""}
                      disabled={!selectedMajorProgramId || !selectedMajorProgram?.offerings?.length}
                    >
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn loại hình đào tạo" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {!selectedMajorProgram?.offerings?.length ? (
                          <div className="p-2 text-sm text-muted-foreground">
                            Không có loại hình đào tạo
                          </div>
                        ) : (
                          selectedMajorProgram.offerings.map((offering) => (
                            <SelectItem key={offering.id} value={offering.id.toString()}>
                              {offering.offering_type}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Chọn loại hình đào tạo (Chính quy, Liên thông, v.v.)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {/* Dropdown 3: Admission Criterion */}
              <FormField
                control={form.control}
                name="criterion_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Phương thức xét tuyển *</FormLabel>
                    {academicInfoLoading ? (
                      <Skeleton className="h-10 w-full" />
                    ) : (
                      <Select
                        onValueChange={(value) => {
                          field.onChange(value || null);
                          // Reset and initialize scores & checklist
                          const criterion = admissionCriteria.find((c) => c.id === value);
                          if (criterion) {
                            // Initialize scores
                            const scores: Record<string, number | null> = {};
                            if (criterion.subject_groups) {
                              criterion.subject_groups.forEach((subject) => {
                                scores[subject] = null;
                              });
                            }
                            form.setValue("documents.scores", scores);

                            // Initialize checklist
                            const checklist: ChecklistItem[] = [];
                            if (criterion.required_documents) {
                              criterion.required_documents.forEach((doc) => {
                                checklist.push({
                                  code: doc.code,
                                  label: doc.label,
                                  status: "missing",
                                  submission_type: "N/A",
                                  notes: "",
                                });
                              });
                            }
                            form.setValue("documents.checklist", checklist);
                          }
                        }}
                        value={field.value || ""}
                        disabled={!selectedOfferingId || !admissionCriteria.length}
                      >
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn phương thức xét tuyển" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {!admissionCriteria.length ? (
                            <div className="p-2 text-sm text-muted-foreground">
                              Không có phương thức xét tuyển
                            </div>
                          ) : (
                            admissionCriteria.map((criterion) => (
                              <SelectItem key={criterion.id} value={criterion.id}>
                                {criterion.method_name}
                              </SelectItem>
                            ))
                          )}
                        </SelectContent>
                      </Select>
                    )}
                    <FormDescription>
                      Chọn phương thức xét tuyển (Học bạ, Thi đại học, v.v.)
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>

          {/* Card 2: Điểm xét tuyển */}
          {selectedCriterion && selectedCriterion.subject_groups && (
            <Card>
              <CardHeader>
                <CardTitle>Điểm xét tuyển</CardTitle>
                <CardDescription>
                  Nhập điểm các môn xét tuyển
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-4 md:grid-cols-3">
                  {selectedCriterion.subject_groups.map((subject) => (
                    <FormField
                      key={subject}
                      control={form.control}
                      name={`documents.scores.${subject}` as any}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>{subject}</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              step="0.1"
                              min="0"
                              max="10"
                              placeholder="0.0"
                              {...field}
                              value={field.value ?? ""}
                              onChange={(e) => {
                                const value = e.target.value;
                                field.onChange(value === "" ? null : parseFloat(value));
                              }}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Card 3: Checklist Hồ sơ */}
          {selectedCriterion && (
            <Card>
              <CardHeader>
                <CardTitle>Checklist Hồ sơ</CardTitle>
                <CardDescription>
                  Theo dõi tình trạng nộp hồ sơ
                </CardDescription>
              </CardHeader>
              <CardContent>
                <DocumentChecklist
                  control={form.control}
                  admissionMethod={selectedCriterion}
                />
              </CardContent>
            </Card>
          )}

          {/* Card 4: Trạng thái Hồ sơ */}
          <Card>
            <CardHeader>
              <CardTitle>Trạng thái Hồ sơ</CardTitle>
              <CardDescription>
                Cập nhật trạng thái xử lý hồ sơ
              </CardDescription>
            </CardHeader>
            <CardContent>
              <FormField
                control={form.control}
                name="status"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Trạng thái *</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue placeholder="Chọn trạng thái" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="pending">Chờ xử lý</SelectItem>
                        <SelectItem value="missing_documents">Chờ bổ sung</SelectItem>
                        <SelectItem value="completed">Đã đủ hồ sơ</SelectItem>
                        <SelectItem value="passed">Đạt</SelectItem>
                        <SelectItem value="failed">Trượt</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      Trạng thái hiện tại của hồ sơ tuyển sinh
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>

          {/* Submit Button */}
          <div className="flex justify-end">
            <Button type="submit" disabled={updateApplication.isPending}>
              {updateApplication.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              <Save className="mr-2 h-4 w-4" />
              Lưu Hồ sơ
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}
