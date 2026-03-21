// src/components/admin/CollaboratorDialog.tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { useForm, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Check, ChevronDown, ChevronsUpDown, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
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
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import {
  useCreateCollaborator,
  useUpdateCollaborator,
} from "@/hooks/useCollaborators";
import { useAdminUsersList } from "@/hooks/useAdminUsers";
import { SmartUnitSelector } from "@/components/common/selectors";
import {
  collaboratorCreateSchema,
  collaboratorOfficerCreateSchema,
  collaboratorUpdateSchema,
  type CollaboratorCreateFormData,
  type CollaboratorUpdateFormData,
} from "@/lib/zod/collaborator";
import type { Collaborator } from "@/types/collaborator.types";

interface CollaboratorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  collaborator?: Collaborator | null;
  mode: "create" | "edit";
  isOfficerMode?: boolean;
}

// Unified form type covering both create and edit modes
type CollaboratorFormData = {
  full_name: string;
  phone: string;
  email: string | null | undefined;
  unit_id: number | null | undefined;
  user_id?: number | null;
  managed_by_officer_id?: number | null;
  id_card_number: string | null | undefined;
  bank_account: string | null | undefined;
  bank_name: string | null | undefined;
  address: string | null | undefined;
  notes: string | null | undefined;
};

const createDefaults: CollaboratorCreateFormData = {
  full_name: "",
  phone: "",
  email: "",
  unit_id: undefined as unknown as number,
  user_id: null,
  managed_by_officer_id: null,
  id_card_number: "",
  bank_account: "",
  bank_name: "",
  address: "",
  notes: "",
};

export function CollaboratorDialog({
  open,
  onOpenChange,
  collaborator,
  mode,
  isOfficerMode,
}: CollaboratorDialogProps) {
  const [optionalOpen, setOptionalOpen] = useState(false);
  const [officerComboOpen, setOfficerComboOpen] = useState(false);

  const createMutation = useCreateCollaborator();
  const updateMutation = useUpdateCollaborator();

  const isCreate = mode === "create";
  const isEdit = mode === "edit";
  const isOfficerCreate = isOfficerMode && isCreate;

  const form = useForm<CollaboratorFormData>({
    resolver: zodResolver(
      isOfficerCreate
        ? collaboratorOfficerCreateSchema
        : isCreate
          ? collaboratorCreateSchema
          : collaboratorUpdateSchema
    ) as Resolver<CollaboratorFormData>,
    defaultValues: createDefaults,
  });

  // Watch unit_id to filter officers by selected unit (skip for officer create)
  const watchedUnitId = form.watch("unit_id");

  // Fetch officers filtered by selected unit (skip entirely for officer create)
  const { data: usersData, isLoading: usersLoading } = useAdminUsersList(
    {
      page_size: 100,
      status: "active",
      unit_id: watchedUnitId || undefined,
      include_children: true,
    },
    { enabled: !isOfficerCreate }
  );

  const officers = useMemo(() => {
    if (!usersData?.users) return [];
    return usersData.users.filter((u) =>
      ["officer", "manager", "admin"].includes(u.role)
    );
  }, [usersData]);

  // Clear officer selection when unit changes and officer no longer in list
  useEffect(() => {
    const currentOfficerId = form.getValues("managed_by_officer_id");
    if (currentOfficerId && officers.length > 0) {
      const stillValid = officers.some((o) => o.id === currentOfficerId);
      if (!stillValid) {
        form.setValue("managed_by_officer_id", null);
      }
    }
  }, [officers, form]);

  // Reset form when dialog opens/closes or collaborator changes
  useEffect(() => {
    if (!open) {
      setOptionalOpen(false);
      return;
    }

    if (isEdit && collaborator) {
      form.reset({
        full_name: collaborator.full_name,
        phone: collaborator.phone,
        email: collaborator.email ?? "",
        unit_id: collaborator.unit_id,
        user_id: collaborator.user_id ?? null,
        managed_by_officer_id: collaborator.managed_by_officer_id ?? null,
        id_card_number: collaborator.id_card_number ?? "",
        bank_account: collaborator.bank_account ?? "",
        bank_name: collaborator.bank_name ?? "",
        address: collaborator.address ?? "",
        notes: collaborator.notes ?? "",
      });
      // Open optional section if any optional field has a value
      const hasOptionalData =
        collaborator.managed_by_officer_id != null ||
        collaborator.id_card_number != null ||
        collaborator.bank_account != null ||
        collaborator.bank_name != null ||
        collaborator.address != null ||
        collaborator.notes != null;
      setOptionalOpen(hasOptionalData);
    } else if (isCreate) {
      form.reset(createDefaults);
      setOptionalOpen(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, collaborator?.id, isEdit, isCreate]);

  const handleDialogOpenChange = (newOpen: boolean) => {
    onOpenChange(newOpen);
  };

  function onSubmit(values: CollaboratorFormData) {
    const onSuccessCallback = () => {
      handleDialogOpenChange(false);
      form.reset();
    };

    if (isCreate) {
      createMutation.mutate(values as CollaboratorCreateFormData, {
        onSuccess: onSuccessCallback,
      });
    } else if (collaborator) {
      updateMutation.mutate(
        { id: collaborator.id, data: values as CollaboratorUpdateFormData },
        { onSuccess: onSuccessCallback },
      );
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>
            {isOfficerCreate
              ? "Đề xuất CTV mới"
              : isCreate
                ? "Tạo Cộng tác viên Mới"
                : "Chỉnh sửa Cộng tác viên"}
          </DialogTitle>
          <DialogDescription>
            {isOfficerCreate
              ? "CTV sẽ ở trạng thái chờ duyệt cho đến khi được quản lý phê duyệt."
              : isCreate
                ? "Thêm cộng tác viên mới vào hệ thống. Các trường có dấu * là bắt buộc."
                : "Cập nhật thông tin cộng tác viên."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* ===== Required fields ===== */}

            {/* Full Name */}
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Họ tên *</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Nguyễn Văn A"
                      autoComplete="name"
                      disabled={isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Phone */}
            <FormField
              control={form.control}
              name="phone"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Số điện thoại *</FormLabel>
                  <FormControl>
                    <Input
                      type="tel"
                      placeholder="0912345678"
                      autoComplete="tel"
                      disabled={isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Email */}
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="example@email.com"
                      autoComplete="email"
                      disabled={isPending}
                      {...field}
                      value={field.value ?? ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Unit (hidden for officer create — backend auto-fills) */}
            {!isOfficerCreate && (
              <FormField
                control={form.control}
                name="unit_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Đơn vị *</FormLabel>
                    <FormControl>
                      <SmartUnitSelector
                        value={field.value ? String(field.value) : undefined}
                        onChange={(val) => field.onChange(val ? Number(val) : undefined)}
                        placeholder="Chọn đơn vị"
                        disabled={isPending}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* ===== Optional fields (collapsible) ===== */}
            <Collapsible open={optionalOpen} onOpenChange={setOptionalOpen}>
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="w-full justify-between"
                >
                  Thông tin bổ sung
                  <ChevronDown
                    className={`h-4 w-4 transition-transform ${optionalOpen ? "rotate-180" : ""}`}
                    aria-hidden="true"
                  />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="space-y-4 pt-2">
                {/* Managed by officer (hidden for officer create — backend auto-fills) */}
                {!isOfficerCreate && (
                  <FormField
                    control={form.control}
                    name="managed_by_officer_id"
                    render={({ field }) => {
                      const selectedOfficer = officers.find(
                        (o) => o.id === field.value
                      );
                      return (
                        <FormItem>
                          <FormLabel>Nhân viên quản lý</FormLabel>
                          <Popover
                            open={officerComboOpen}
                            onOpenChange={setOfficerComboOpen}
                          >
                            <PopoverTrigger asChild>
                              <FormControl>
                                <Button
                                  variant="outline"
                                  role="combobox"
                                  aria-expanded={officerComboOpen}
                                  disabled={isPending || usersLoading}
                                  className={cn(
                                    "w-full justify-between font-normal",
                                    !field.value && "text-muted-foreground"
                                  )}
                                >
                                  <span className="truncate">
                                    {usersLoading
                                      ? "Đang tải…"
                                      : selectedOfficer
                                        ? `${selectedOfficer.full_name || selectedOfficer.username} (${selectedOfficer.role})`
                                        : "Chọn nhân viên quản lý"}
                                  </span>
                                  <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                                </Button>
                              </FormControl>
                            </PopoverTrigger>
                            <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
                              <Command>
                                <CommandInput placeholder="Tìm theo tên…" />
                                <CommandEmpty>Không tìm thấy nhân viên.</CommandEmpty>
                                <CommandGroup className="max-h-[200px] overflow-auto">
                                  {/* Option to clear selection */}
                                  <CommandItem
                                    value="__none__"
                                    onSelect={() => {
                                      field.onChange(null);
                                      setOfficerComboOpen(false);
                                    }}
                                  >
                                    <Check
                                      className={cn(
                                        "mr-2 h-4 w-4",
                                        !field.value ? "opacity-100" : "opacity-0"
                                      )}
                                    />
                                    <span className="text-muted-foreground">Không có</span>
                                  </CommandItem>
                                  {officers.map((officer) => (
                                    <CommandItem
                                      key={officer.id}
                                      value={`${officer.full_name ?? ""} ${officer.username} ${officer.role}`}
                                      onSelect={() => {
                                        field.onChange(officer.id);
                                        setOfficerComboOpen(false);
                                      }}
                                    >
                                      <Check
                                        className={cn(
                                          "mr-2 h-4 w-4",
                                          field.value === officer.id
                                            ? "opacity-100"
                                            : "opacity-0"
                                        )}
                                      />
                                      <div>
                                        <span className="font-medium">
                                          {officer.full_name || officer.username}
                                        </span>
                                        <span className="ml-2 text-xs text-muted-foreground">
                                          ({officer.role})
                                        </span>
                                      </div>
                                    </CommandItem>
                                  ))}
                                </CommandGroup>
                              </Command>
                            </PopoverContent>
                          </Popover>
                          <FormMessage />
                        </FormItem>
                      );
                    }}
                  />
                )}

                {/* ID Card Number */}
                <FormField
                  control={form.control}
                  name="id_card_number"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>CCCD/CMND</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="Số CCCD/CMND"
                          disabled={isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Bank Account */}
                <FormField
                  control={form.control}
                  name="bank_account"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Số tài khoản</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="Số tài khoản ngân hàng"
                          disabled={isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Bank Name */}
                <FormField
                  control={form.control}
                  name="bank_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Ngân hàng</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="Tên ngân hàng"
                          disabled={isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Address */}
                <FormField
                  control={form.control}
                  name="address"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Địa chỉ</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="Địa chỉ liên hệ"
                          disabled={isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {/* Notes */}
                <FormField
                  control={form.control}
                  name="notes"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Ghi chú</FormLabel>
                      <FormControl>
                        <Textarea
                          placeholder="Ghi chú thêm về cộng tác viên"
                          rows={3}
                          disabled={isPending}
                          {...field}
                          value={field.value ?? ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </CollapsibleContent>
            </Collapsible>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleDialogOpenChange(false)}
                disabled={isPending}
              >
                Hủy
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                    Đang lưu…
                  </>
                ) : isOfficerCreate ? (
                  "Đề xuất"
                ) : isCreate ? (
                  "Tạo CTV"
                ) : (
                  "Lưu thay đổi"
                )}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
