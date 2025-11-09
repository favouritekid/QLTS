// src/components/admin/organization/MajorDialog.tsx
"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import {
  useOrganizationUnits,
  useCreateMajor,
  useUpdateMajor,
} from "@/hooks/useOrganization";
import type {
  Major,
  MajorCreate,
  MajorUpdate,
} from "@/types/organization.types";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const majorFormSchema = z.object({
  name: z
    .string()
    .min(1, "Tên ngành học là bắt buộc")
    .min(3, "Tên ngành học phải có ít nhất 3 ký tự")
    .max(200, "Tên ngành học không được vượt quá 200 ký tự"),
  code: z
    .string()
    .min(1, "Mã ngành học là bắt buộc")
    .min(2, "Mã ngành học phải có ít nhất 2 ký tự")
    .max(50, "Mã ngành học không được vượt quá 50 ký tự")
    .regex(/^[A-Z0-9_-]+$/, "Mã ngành chỉ bao gồm chữ in hoa, số, dấu gạch ngang và gạch dưới"),
  description: z.string().max(500, "Mô tả không được vượt quá 500 ký tự").optional(),
  unit_id: z.string().min(1, "Đơn vị quản lý là bắt buộc"), // String vì Select dùng string
});

type MajorFormValues = z.infer<typeof majorFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface MajorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  major?: Major | null; // null = create mode, non-null = edit mode
  preselectedUnitId?: number | null; // Pre-select unit when creating
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function MajorDialog({
  open,
  onOpenChange,
  major,
  preselectedUnitId,
}: MajorDialogProps) {
  const isEditMode = !!major;

  // Queries
  const { data: allUnits = [], isLoading: unitsLoading } = useOrganizationUnits();

  // Mutations
  const createMutation = useCreateMajor();
  const updateMutation = useUpdateMajor();

  // Form
  const form = useForm<MajorFormValues>({
    resolver: zodResolver(majorFormSchema),
    defaultValues: {
      name: "",
      code: "",
      description: "",
      unit_id: "",
    },
  });

  // Populate form when editing or preselecting
  useEffect(() => {
    if (open) {
      if (isEditMode && major) {
        form.reset({
          name: major.name || "",
          code: major.code || "",
          description: major.description || "",
          unit_id: String(major.unit_id),
        });
      } else {
        form.reset({
          name: "",
          code: "",
          description: "",
          unit_id: preselectedUnitId ? String(preselectedUnitId) : "",
        });
      }
    }
  }, [open, isEditMode, major, preselectedUnitId, form]);

  // Handle form submission
  const onSubmit = async (values: MajorFormValues) => {
    const payload = {
      name: values.name,
      code: values.code.toUpperCase(), // Ensure uppercase
      description: values.description || null,
      unit_id: Number(values.unit_id),
    };

    try {
      if (isEditMode && major) {
        await updateMutation.mutateAsync({
          id: major.id,
          data: payload as MajorUpdate,
        });
      } else {
        await createMutation.mutateAsync(payload as MajorCreate);
      }

      // Close dialog on success
      onOpenChange(false);
      form.reset();
    } catch (error) {
      // Error handling is done in mutation hooks (toast)
      console.error("Form submission error:", error);
    }
  };

  // Check if mutation is in progress
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  // Helper to format code as user types (uppercase, no spaces)
  const handleCodeChange = (value: string) => {
    const formatted = value.toUpperCase().replace(/\s+/g, "_");
    form.setValue("code", formatted, { shouldValidate: true });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Chỉnh sửa ngành học" : "Tạo ngành học mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật thông tin của ngành học"
              : "Nhập thông tin để tạo ngành học mới"}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Name Field */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Tên ngành học <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Công nghệ Thông tin"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Code Field */}
            <FormField
              control={form.control}
              name="code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Mã ngành <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: CNTT"
                      {...field}
                      onChange={(e) => handleCodeChange(e.target.value)}
                      disabled={isSubmitting || isEditMode} // Disable in edit mode
                      className="uppercase"
                    />
                  </FormControl>
                  <FormDescription>
                    Chữ in hoa, số, gạch ngang hoặc gạch dưới
                    {isEditMode && " (không thể thay đổi)"}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Unit Field */}
            <FormField
              control={form.control}
              name="unit_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Đơn vị quản lý <span className="text-red-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting || unitsLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn đơn vị quản lý" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {allUnits.map((unit) => (
                        <SelectItem key={unit.id} value={String(unit.id)}>
                          {unit.name} ({unit.type})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Đơn vị tổ chức quản lý ngành học này
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Description Field */}
            <FormField
              control={form.control}
              name="description"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mô tả</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder="Mô tả về ngành học..."
                      className="resize-none"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={isSubmitting}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditMode ? "Cập nhật" : "Tạo mới"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
