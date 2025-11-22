"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

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
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

import { SmartUnitSelector, SmartOfferingSelector } from "@/components/common/selectors";

// Schema validation
const formSchema = z.object({
  offering_id: z.string().min(1, "Vui lòng chọn chương trình đào tạo"),
  unit_id: z.string().min(1, "Vui lòng chọn đơn vị tiếp nhận"),
  weight: z.number().min(1, "Trọng số tối thiểu là 1"),
  priority: z.number().min(1, "Độ ưu tiên tối thiểu là 1"),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof formSchema>;

interface DistributionRule {
  id: number;
  offering_id: number;
  unit_id: number;
  weight: number;
  priority: number;
  is_active: boolean;
}

interface DistributionRuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rule: DistributionRule | null;
}

export function DistributionRuleDialog({ open, onOpenChange, rule }: DistributionRuleDialogProps) {
  const queryClient = useQueryClient();
  const isEditing = !!rule;

  // === FORM SETUP ===
  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      offering_id: "",
      unit_id: "",
      weight: 1,
      priority: 1,
      is_active: true,
    },
  });

  useEffect(() => {
    if (open) {
      if (rule) {
        form.reset({
          offering_id: rule.offering_id.toString(),
          unit_id: rule.unit_id.toString(),
          weight: rule.weight,
          priority: rule.priority,
          is_active: rule.is_active,
        });
      } else {
        form.reset({
          offering_id: "",
          unit_id: "",
          weight: 1,
          priority: 1,
          is_active: true,
        });
      }
    }
  }, [open, rule, form]);

  // === MUTATION ===
  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = {
        ...values,
        offering_id: parseInt(values.offering_id),
        unit_id: parseInt(values.unit_id),
      };

      if (isEditing) {
        return api.put(`/api/admin/distribution-rules/${rule.id}`, payload);
      } else {
        return api.post("/api/admin/distribution-rules", payload);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "distribution-rules"] });
      toast.success(isEditing ? "Cập nhật thành công" : "Tạo mới thành công");
      onOpenChange(false);
    },
    onError: (error: unknown) => {
      const msg = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Có lỗi xảy ra";
      toast.error(msg);
    },
  });

  const onSubmit = (values: FormValues) => mutation.mutate(values);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Sửa Luật Phân Phối" : "Thêm Luật Mới"}</DialogTitle>
          <DialogDescription>
            Cấu hình điều phối Lead tự động cho từng chương trình.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Offering Select with Hierarchy Tree */}
            <FormField
              control={form.control}
              name="offering_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Chương trình đào tạo</FormLabel>
                  <FormControl>
                    <SmartOfferingSelector
                      value={field.value}
                      onChange={(val) => field.onChange(val || "")}
                      placeholder="Chọn chương trình..."
                      disabled={isEditing}
                      variant="select"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Unit Select with Hierarchy */}
            <FormField
              control={form.control}
              name="unit_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đơn vị tiếp nhận</FormLabel>
                  <FormControl>
                    <SmartUnitSelector
                      value={field.value}
                      onChange={(val) => field.onChange(val || "")}
                      placeholder="Chọn đơn vị..."
                      disabled={isEditing}
                      variant="select"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-2 gap-4">
              <FormField
                control={form.control}
                name="weight"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Trọng số (Weight)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        {...field}
                        onChange={(e) => field.onChange(Number(e.target.value))}
                      />
                    </FormControl>
                    <FormDescription className="text-[11px]">
                      Tỷ lệ được chia (VD: 5 = 5 phần).
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="priority"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Thứ tự ưu tiên</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        {...field}
                        onChange={(e) => field.onChange(Number(e.target.value))}
                      />
                    </FormControl>
                    <FormDescription className="text-[11px]">
                      1 = Ưu tiên cao nhất.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <FormField
              control={form.control}
              name="is_active"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border p-3 shadow-sm">
                  <div className="space-y-0.5">
                    <FormLabel className="text-base">Kích hoạt</FormLabel>
                    <FormDescription>
                      Cho phép tham gia vòng chia Lead.
                    </FormDescription>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Hủy
              </Button>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {isEditing ? "Lưu thay đổi" : "Tạo mới"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
