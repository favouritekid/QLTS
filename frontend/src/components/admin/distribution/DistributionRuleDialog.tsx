"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";

// Schema validation
const formSchema = z.object({
  offering_id: z.string().min(1, "Vui lòng chọn chương trình đào tạo"),
  unit_id: z.string().min(1, "Vui lòng chọn đơn vị tiếp nhận"),
  weight: z.coerce.number().min(1, "Trọng số tối thiểu là 1"),
  priority: z.coerce.number().min(1, "Độ ưu tiên tối thiểu là 1"),
  is_active: z.boolean().default(true),
});

type FormValues = z.infer<typeof formSchema>;

interface DistributionRuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rule: any | null;
}

export function DistributionRuleDialog({ open, onOpenChange, rule }: DistributionRuleDialogProps) {
  const queryClient = useQueryClient();
  const isEditing = !!rule;

  // === 🔥 TỐI ƯU: TÁI SỬ DỤNG API CÓ SẴN (REUSE) ===

  // 1. Fetch Offerings (Reuse API /program-offerings)
  const { data: offerings, isLoading: isLoadingOfferings } = useQuery({
    queryKey: ["organization", "offerings", "all"],
    queryFn: async () => {
      // Gọi API với limit lớn để giả lập "Get All"
      const res = await api.get("/api/organization/program-offerings", {
        params: { skip: 0, limit: 1000 },
      });

      // Xử lý response đa hình (Array hoặc Paginated Object)
      if (Array.isArray(res.data)) return res.data;
      if (res.data && Array.isArray(res.data.items)) return res.data.items;
      return [];
    },
    enabled: open, // Chỉ gọi khi mở dialog
    staleTime: 5 * 60 * 1000, // Cache 5 phút
  });

  // 2. Fetch Units (Reuse API /units)
  const { data: units, isLoading: isLoadingUnits } = useQuery({
    queryKey: ["organization", "units", "all"],
    queryFn: async () => {
      const res = await api.get("/api/organization/units", {
        params: { skip: 0, limit: 1000 },
      });

      if (Array.isArray(res.data)) return res.data;
      if (res.data && Array.isArray(res.data.items)) return res.data.items;
      return [];
    },
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

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
    onError: (error: any) => {
      // Xử lý lỗi trùng lặp từ Backend
      const msg = error.response?.data?.detail || "Có lỗi xảy ra";
      toast.error(msg);
    },
  });

  const onSubmit = (values: FormValues) => mutation.mutate(values);
  const isLoadingDropdowns = isLoadingOfferings || isLoadingUnits;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Sửa Luật Phân Phối" : "Thêm Luật Mới"}</DialogTitle>
          <DialogDescription>
            Cấu hình điều phối Lead tự động cho từng chương trình.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Offering Select */}
            <FormField
              control={form.control}
              name="offering_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Chương trình (Offering)</FormLabel>
                  <Select
                    disabled={isEditing || isLoadingDropdowns}
                    onValueChange={field.onChange}
                    value={field.value}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue
                          placeholder={isLoadingDropdowns ? "Đang tải..." : "Chọn chương trình..."}
                        />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {offerings?.map((item: any) => (
                        <SelectItem key={item.id} value={item.id.toString()}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Unit Select */}
            <FormField
              control={form.control}
              name="unit_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Đơn vị tiếp nhận (Unit)</FormLabel>
                  <Select
                    disabled={isEditing || isLoadingDropdowns}
                    onValueChange={field.onChange}
                    value={field.value}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue
                          placeholder={isLoadingDropdowns ? "Đang tải..." : "Chọn đơn vị..."}
                        />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {units?.map((item: any) => (
                        <SelectItem key={item.id} value={item.id.toString()}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                      <Input type="number" min={1} {...field} />
                    </FormControl>
                    <FormDescription className="text-[11px]">
                      Tỷ lệ được chia (VD: 5).
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
                      <Input type="number" min={1} {...field} />
                    </FormControl>
                    <FormDescription className="text-[11px]">1 = Cao nhất.</FormDescription>
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
                    <FormDescription>Cho phép tham gia vòng chia Lead.</FormDescription>
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
