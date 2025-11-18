// src/components/leads/DocumentChecklist.tsx
"use client";

import { useEffect } from "react";
import { Control, useFieldArray, FieldValues } from "react-hook-form";
import {
  FormControl,
  FormField,
  FormItem,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AdmissionCriterion } from "@/types/organization.types";
import type { ChecklistItem } from "@/types/lead.types";

interface DocumentChecklistProps {
  control: Control<FieldValues>;
  admissionMethod: AdmissionCriterion;
}

export function DocumentChecklist({ control, admissionMethod }: DocumentChecklistProps) {
  const { fields, replace } = useFieldArray({
    control,
    name: "documents.checklist",
  });

  // Update checklist when admission method changes
  useEffect(() => {
    if (admissionMethod.required_documents) {
      const newChecklist: ChecklistItem[] = admissionMethod.required_documents.map((doc) => ({
        code: doc.code,
        label: doc.label,
        status: "missing" as const,
        submission_type: "N/A" as const,
        notes: "",
      }));
      replace(newChecklist);
    } else {
      replace([]);
    }
  }, [admissionMethod.id, admissionMethod.required_documents, replace]);

  if (!fields.length) {
    return (
      <div className="text-center text-muted-foreground py-8">
        Không có hồ sơ bắt buộc cho phương thức này
      </div>
    );
  }

  return (
    <div className="border rounded-lg overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[250px]">Tên Hồ sơ</TableHead>
            <TableHead className="w-[150px]">Trạng thái</TableHead>
            <TableHead className="w-[150px]">Loại hồ sơ</TableHead>
            <TableHead>Ghi chú</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {fields.map((field, index) => (
            <TableRow key={field.id}>
              {/* Tên Hồ sơ (Readonly) */}
              <TableCell className="font-medium">
                <FormField
                  control={control}
                  name={`documents.checklist.${index}.label`}
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <div className="text-sm">{field.value}</div>
                      </FormControl>
                    </FormItem>
                  )}
                />
              </TableCell>

              {/* Trạng thái */}
              <TableCell>
                <FormField
                  control={control}
                  name={`documents.checklist.${index}.status`}
                  render={({ field }) => (
                    <FormItem>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="missing">Missing</SelectItem>
                          <SelectItem value="submitted">Submitted</SelectItem>
                          <SelectItem value="verified">Verified</SelectItem>
                          <SelectItem value="rejected">Rejected</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </TableCell>

              {/* Loại hồ sơ */}
              <TableCell>
                <FormField
                  control={control}
                  name={`documents.checklist.${index}.submission_type`}
                  render={({ field }) => (
                    <FormItem>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="N/A">N/A</SelectItem>
                          <SelectItem value="photocopy">Photocopy</SelectItem>
                          <SelectItem value="notarized">Notarized</SelectItem>
                          <SelectItem value="original">Original</SelectItem>
                          <SelectItem value="incomplete">Incomplete</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </TableCell>

              {/* Ghi chú */}
              <TableCell>
                <FormField
                  control={control}
                  name={`documents.checklist.${index}.notes`}
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Input
                          placeholder="Nhập ghi chú..."
                          {...field}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
