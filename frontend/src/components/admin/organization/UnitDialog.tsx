// src/components/admin/organization/UnitDialog.tsx
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
  useOrganizationUnitTypes,
  useCreateUnit,
  useUpdateUnit,
  wouldCreateCircularDependency,
} from "@/hooks/useOrganization";
import type {
  OrganizationUnit,
  OrganizationUnitCreate,
  OrganizationUnitUpdate,
} from "@/types/organization.types";

// =====================================================================
// FORM VALIDATION SCHEMA
// =====================================================================

const unitFormSchema = z.object({
  name: z
    .string()
    .min(1, "Tên đơn vị là bắt buộc")
    .min(3, "Tên đơn vị phải có ít nhất 3 ký tự")
    .max(200, "Tên đơn vị không được vượt quá 200 ký tự"),
  type: z
    .string()
    .min(1, "Loại đơn vị là bắt buộc")
    .max(50, "Loại đơn vị không được vượt quá 50 ký tự"),
  description: z.string().max(500, "Mô tả không được vượt quá 500 ký tự").optional(),
  parent_id: z.string().optional(), // String vì Select component dùng string
});

type UnitFormValues = z.infer<typeof unitFormSchema>;

// =====================================================================
// COMPONENT PROPS
// =====================================================================

interface UnitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  unit?: OrganizationUnit | null; // null = create mode, non-null = edit mode
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function UnitDialog({ open, onOpenChange, unit }: UnitDialogProps) {
  const isEditMode = !!unit;

  // Queries
  const { data: allUnits = [], isLoading: unitsLoading } = useOrganizationUnits();
  const { data: unitTypes = [], isLoading: typesLoading } = useOrganizationUnitTypes();

  // Mutations
  const createMutation = useCreateUnit();
  const updateMutation = useUpdateUnit();

  // Form
  const form = useForm<UnitFormValues>({
    resolver: zodResolver(unitFormSchema),
    defaultValues: {
      name: "",
      type: "",
      description: "",
      parent_id: undefined,
    },
  });

  // Populate form when editing
  useEffect(() => {
    if (open) {
      if (isEditMode && unit) {
        form.reset({
          name: unit.name || "",
          type: unit.type || "",
          description: unit.description || "",
          parent_id: unit.parent_id ? String(unit.parent_id) : undefined,
        });
      } else {
        form.reset({
          name: "",
          type: "",
          description: "",
          parent_id: undefined,
        });
      }
    }
  }, [open, isEditMode, unit, form]);

  // Handle form submission
  const onSubmit = async (values: UnitFormValues) => {
    // Convert parent_id from string to number
    const parent_id = values.parent_id ? Number(values.parent_id) : null;

    // Validate circular dependency
    if (isEditMode && unit && parent_id) {
      if (wouldCreateCircularDependency(parent_id, unit.id, allUnits)) {
        form.setError("parent_id", {
          message: "Không thể chọn đơn vị con làm đơn vị cha (tạo vòng lặp)",
        });
        return;
      }
    }

    const payload = {
      name: values.name,
      type: values.type,
      description: values.description || null,
      parent_id,
    };

    try {
      if (isEditMode && unit) {
        await updateMutation.mutateAsync({
          id: unit.id,
          data: payload as OrganizationUnitUpdate,
        });
      } else {
        await createMutation.mutateAsync(payload as OrganizationUnitCreate);
      }

      // Close dialog on success
      onOpenChange(false);
      form.reset();
    } catch (error) {
      // Error handling is done in mutation hooks (toast)
      console.error("Form submission error:", error);
    }
  };

  // Get units available as parent (exclude self and descendants in edit mode)
  const getAvailableParentUnits = (): OrganizationUnit[] => {
    if (!isEditMode || !unit) return allUnits;

    // Get all descendant IDs
    const excludedIds = new Set<number>([unit.id]);

    const collectDescendants = (unitId: number) => {
      allUnits.forEach((u) => {
        if (u.parent_id === unitId) {
          excludedIds.add(u.id);
          collectDescendants(u.id); // Recursive
        }
      });
    };

    collectDescendants(unit.id);

    // Filter out excluded units
    return allUnits.filter((u) => !excludedIds.has(u.id));
  };

  const availableParentUnits = getAvailableParentUnits();

  // Check if mutation is in progress
  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {isEditMode ? "Chỉnh sửa đơn vị tổ chức" : "Tạo đơn vị tổ chức mới"}
          </DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Cập nhật thông tin của đơn vị tổ chức"
              : "Nhập thông tin để tạo đơn vị tổ chức mới"}
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
                    Tên đơn vị <span className="text-red-500">*</span>
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="VD: Khoa Công nghệ Thông tin"
                      {...field}
                      disabled={isSubmitting}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Type Field */}
            <FormField
              control={form.control}
              name="type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Loại đơn vị <span className="text-red-500">*</span>
                  </FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                    disabled={isSubmitting || typesLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn loại đơn vị" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {typesLoading ? (
                        <SelectItem value="loading" disabled>
                          Đang tải...
                        </SelectItem>
                      ) : unitTypes.length === 0 ? (
                        <SelectItem value="empty" disabled>
                          Không có dữ liệu
                        </SelectItem>
                      ) : (
                        unitTypes.map((type) => (
                          <SelectItem key={type} value={type}>
                            {type}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Chọn loại hình tổ chức phù hợp
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Parent Unit Field */}
            <FormField
              control={form.control}
              name="parent_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đơn vị cha</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isSubmitting || unitsLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn đơn vị cha (nếu có)" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="none">Không có (cấp cao nhất)</SelectItem>
                      {availableParentUnits.map((parentUnit) => (
                        <SelectItem key={parentUnit.id} value={String(parentUnit.id)}>
                          {parentUnit.name} ({parentUnit.type})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Nếu bỏ trống, đơn vị này sẽ là cấp cao nhất
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
                      placeholder="Mô tả về đơn vị..."
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
