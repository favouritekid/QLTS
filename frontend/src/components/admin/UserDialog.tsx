// src/components/admin/UserDialog.tsx
"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useForm, type Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Camera, Loader2 } from "lucide-react";

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
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { PasswordStrengthIndicator } from "./PasswordStrengthIndicator";
import { useAdminCreateUser, useAdminUpdateUser } from "@/hooks/useAdminUsers";
import { useRoles } from "@/hooks/usePolicies";
import type { User } from "@/types/api.types";
import { getAvatarUrl } from "@/lib/utils";

/**
 * Extract role name from Casbin format (e.g., "role:admin" -> "admin")
 * If no prefix, returns as-is
 */
function extractRoleName(roleWithPrefix: string): string {
  return roleWithPrefix.startsWith("role:")
    ? roleWithPrefix.substring(5)
    : roleWithPrefix;
}

/**
 * Capitalize first letter for display (e.g., "admin" -> "Admin")
 */
function capitalizeRole(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

// Validation schemas - Using string instead of enum to support dynamic roles
const createUserSchema = z.object({
  username: z
    .string()
    .min(3, "Tên đăng nhập phải có ít nhất 3 ký tự")
    .max(64, "Tên đăng nhập không được quá 64 ký tự")
    .regex(/^[a-zA-Z0-9_-]+$/, "Tên đăng nhập chỉ chứa chữ cái, số, gạch ngang và gạch dưới"),
  email: z.string().email("Địa chỉ email không hợp lệ"),
  password: z
    .string()
    .min(12, "Mật khẩu phải có ít nhất 12 ký tự")
    .regex(/[A-Z]/, "Mật khẩu phải chứa chữ cái viết hoa")
    .regex(/[a-z]/, "Mật khẩu phải chứa chữ cái viết thường")
    .regex(/\d/, "Mật khẩu phải chứa số")
    .regex(/[@$!%*?&]/, "Mật khẩu phải chứa ký tự đặc biệt"),
  full_name: z.string().min(1, "Họ tên là bắt buộc").max(120, "Họ tên không được quá 120 ký tự"),
  role: z.string().min(1, "Vai trò là bắt buộc").default("user"),
  status: z.enum(["active", "pending", "banned"]).default("active"),
  avatar: z.instanceof(File).optional(),
});

const editUserSchema = z.object({
  full_name: z.string().max(120, "Họ tên không được quá 120 ký tự").optional(),
  email: z.string().email("Địa chỉ email không hợp lệ"),
  phone_number: z
    .string()
    .regex(
      /^(0|\+?84)(3|5|7|8|9|2)\d{8,9}$/,
      "Số điện thoại không hợp lệ (định dạng VN: 0xxxxxxxxx)"
    )
    .optional()
    .or(z.literal("")),
  role: z.string().min(1, "Vai trò là bắt buộc"),
  status: z.enum(["active", "pending", "banned"]),
  // Trọng số phân công lead cho officer (1-100). coerce vì <input type="number">
  // trả string; default(1) đảm bảo luôn có giá trị hợp lệ kể cả khi field ẩn.
  assignment_weight: z.coerce.number().int().min(1, "Tối thiểu 1").max(100, "Tối đa 100").default(1),
  avatar: z.instanceof(File).optional(),
});

type CreateUserFormValues = z.infer<typeof createUserSchema>;
type EditUserFormValues = z.infer<typeof editUserSchema>;

type UserFormValues = {
  username?: string;
  email: string;
  password?: string;
  full_name?: string;
  phone_number?: string;
  role: string;
  status: "active" | "pending" | "banned";
  assignment_weight?: number;
  avatar?: File;
};

interface UserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user?: User | null;
  mode: "create" | "edit";
}

export function UserDialog({ open, onOpenChange, user, mode }: UserDialogProps) {
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [passwordValue, setPasswordValue] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const createUserMutation = useAdminCreateUser();
  const updateUserMutation = useAdminUpdateUser(user?.id || 0);
  const { data: rolesData, isLoading: rolesLoading } = useRoles();

  const isCreate = mode === "create";
  const isEdit = mode === "edit";

  // Extract available roles from Casbin roles (strip "role:" prefix)
  const availableRoles = useMemo(() => {
    if (!rolesData?.roles) return [];
    return rolesData.roles
      .map(role => extractRoleName(role.name))
      .filter(role => role.length > 0) // Filter out empty strings
      .sort(); // Sort alphabetically
  }, [rolesData]);

  // Form setup - use unified types to avoid union type issues with react-hook-form
  const form = useForm<UserFormValues>({
    resolver: zodResolver(isCreate ? createUserSchema : editUserSchema) as Resolver<UserFormValues>,
    defaultValues: isEdit && user
      ? {
          full_name: user.full_name || "",
          email: user.email,
          phone_number: user.phone_number || "",
          role: user.role, // architecture-allow serialization
          status: user.status,
          assignment_weight: user.assignment_weight ?? 1,
        }
      : {
          username: "",
          email: "",
          password: "",
          full_name: "",
          role: "user" as const,
          status: "active" as const,
        },
  });

  // Reset form and avatar preview when dialog opens or user changes
  useEffect(() => {
    if (!open) {
      // Reset everything when dialog closes
      setAvatarPreview(null);
      setPasswordValue("");
      return;
    }

    if (isEdit && user) {
      form.reset({
        full_name: user.full_name || "",
        email: user.email,
        phone_number: user.phone_number || "",
        role: user.role, // architecture-allow serialization
        status: user.status,
        assignment_weight: user.assignment_weight ?? 1,
      });
      // Clear preview to show current user's avatar from server
      setAvatarPreview(null);
    } else if (isCreate) {
      form.reset({
        username: "",
        email: "",
        password: "",
        full_name: "",
        role: "user" as const,
        status: "active" as const,
      });
      setAvatarPreview(null);
      setPasswordValue("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, user?.id, isEdit, isCreate]);

  // Handle avatar file selection
  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // Validate file type
      if (!file.type.startsWith("image/")) {
        form.setError("avatar", {
          type: "manual",
          message: "Vui lòng chọn tệp hình ảnh hợp lệ",
        });
        return;
      }

      // Validate file size (max 2MB)
      if (file.size > 2 * 1024 * 1024) {
        form.setError("avatar", {
          type: "manual",
          message: "Kích thước ảnh phải nhỏ hơn 2MB",
        });
        return;
      }

      // Set the file in form
      form.setValue("avatar", file);
      form.clearErrors("avatar");

      // Create preview URL
      const reader = new FileReader();
      reader.onloadend = () => {
        setAvatarPreview(reader.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  // Handle dialog open/close changes
  const handleDialogOpenChange = (newOpen: boolean) => {
    onOpenChange(newOpen);
    // State resets are now handled in useEffect
  };

  // Handle form submission
  // ✅ UX FIX (v17): Only close dialog on success, keep open on error
  function onSubmit(values: UserFormValues) {
    // Define success callback - only close dialog when mutation succeeds
    const onSuccessCallback = () => {
      handleDialogOpenChange(false);
      form.reset();
    };

    // Use mutate with inline callbacks instead of mutateAsync
    // This ensures dialog only closes on success
    if (isCreate) {
      createUserMutation.mutate(values as CreateUserFormValues, {
        onSuccess: onSuccessCallback,
        // onError is already handled in the hook (toast notification)
      });
    } else if (user) {
      updateUserMutation.mutate(values as EditUserFormValues, {
        onSuccess: onSuccessCallback,
        // onError is already handled in the hook (toast notification)
      });
    }
  }

  // If user is uploading new avatar, show preview
  // Otherwise show current avatar from server (converted to absolute URL)
  const displayAvatarUrl = avatarPreview || getAvatarUrl(user?.avatar_url);
  const avatarFallback = isEdit && user
    ? user.username.slice(0, 2).toUpperCase()
    : "?";

  const isPending = createUserMutation.isPending || updateUserMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleDialogOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>{isCreate ? "Tạo Người dùng Mới" : "Chỉnh sửa Người dùng"}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Thêm người dùng mới vào hệ thống. Các trường có dấu * là bắt buộc."
              : "Cập nhật thông tin người dùng. Để trống ảnh đại diện để giữ ảnh hiện tại."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Avatar Section */}
            <div className="flex items-center gap-6">
              <div className="relative">
                <Avatar className="h-20 w-20">
                  <AvatarImage src={displayAvatarUrl} alt="User avatar" />
                  <AvatarFallback className="text-lg">{avatarFallback}</AvatarFallback>
                </Avatar>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="bg-primary text-primary-foreground hover:bg-primary/90 absolute bottom-0 right-0 rounded-full p-1.5 shadow-md transition-colors"
                  disabled={isPending}
                  aria-label="Thay đổi ảnh đại diện"
                >
                  <Camera className="h-3 w-3" />
                </button>
              </div>
              <div className="flex-1 space-y-1">
                <p className="text-sm font-medium">Ảnh đại diện</p>
                <p className="text-muted-foreground text-xs">
                  JPG, PNG hoặc GIF. Tối đa 2MB.
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleAvatarChange}
                  className="hidden"
                  disabled={isPending}
                />
                {form.formState.errors.avatar && (
                  <p className="text-destructive text-xs">
                        {String((form.formState.errors.avatar as { message?: string } | undefined)?.message || "Tệp không hợp lệ")}
                  </p>
                )}
              </div>
            </div>

            {/* Username (Create only) */}
            {isCreate && (
              <FormField
                control={form.control}
                name="username"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Tên đăng nhập *</FormLabel>
                    <FormControl>
                      <Input placeholder="nguyenvana" autoComplete="username" disabled={isPending} {...field} />
                    </FormControl>
                    <FormDescription>
                      Phải duy nhất. Chỉ chứa chữ cái, số, dấu gạch ngang và gạch dưới.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Full Name */}
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Họ và tên</FormLabel>
                  <FormControl>
                    <Input placeholder="Nguyễn Văn A" autoComplete="name" disabled={isPending} {...field} />
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
                  <FormLabel>Email *</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="john.doe@example.com"
                      autoComplete="email"
                      disabled={isPending}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Phone Number (Edit only) */}
            {isEdit && (
              <FormField
                control={form.control}
                name="phone_number"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Số điện thoại</FormLabel>
                    <FormControl>
                      <Input
                        type="tel"
                        placeholder="+1 (555) 123-4567"
                        autoComplete="tel"
                        disabled={isPending}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Password (Create only) */}
            {isCreate && (
              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Mật khẩu *</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        placeholder="••••••••"
                        autoComplete="new-password"
                        disabled={isPending}
                        {...field}
                        onChange={(e) => {
                          field.onChange(e);
                          setPasswordValue(e.target.value);
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                    {passwordValue && <PasswordStrengthIndicator password={passwordValue} />}
                  </FormItem>
                )}
              />
            )}

            {/* Role */}
            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Vai trò *</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isPending || rolesLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder={rolesLoading ? "Đang tải vai trò…" : "Chọn vai trò"} />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {rolesLoading ? (
                        <SelectItem value="__radix_loading__" disabled>
                          Đang tải vai trò…
                        </SelectItem>
                      ) : availableRoles.length === 0 ? (
                        <SelectItem value="__radix_empty__" disabled>
                          Không có vai trò nào
                        </SelectItem>
                      ) : (
                        availableRoles.map((role) => (
                          <SelectItem key={role} value={role}>
                            {capitalizeRole(role)}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Xác định những gì người dùng có thể truy cập trong hệ thống.
                    {availableRoles.length > 0 && (
                      <> ({availableRoles.length} vai trò có sẵn)</>
                    )}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Assignment Weight — chỉ khi edit + role đang chọn là officer.
                Dùng form.watch("role") (KHÔNG user.role) để đổi role→officer là
                nhập được weight ngay. Field vẫn trong form state khi ẩn (default 1). */}
            {isEdit && form.watch("role") === "officer" && (
              <FormField
                control={form.control}
                name="assignment_weight"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Trọng số phân công lead</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        max={100}
                        disabled={isPending}
                        {...field}
                        value={field.value ?? 1}
                        onChange={(e) => field.onChange(e.target.value)}
                      />
                    </FormControl>
                    <FormDescription>
                      Officer trọng số cao nhận nhiều lead hơn theo tỉ lệ (1–100, mặc
                      định 1). Không phá trần tải an toàn — chỉ ưu tiên khi còn chỗ.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {/* Status */}
            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Trạng thái *</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    value={field.value}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Chọn trạng thái" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="active">Hoạt động</SelectItem>
                      <SelectItem value="pending">Chờ duyệt</SelectItem>
                      <SelectItem value="banned">Bị khóa</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Người dùng Hoạt động có thể đăng nhập. Người dùng Bị khóa không thể truy cập.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

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
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {isCreate ? "Đang tạo…" : "Đang lưu…"}
                  </>
                ) : (
                  <>{isCreate ? "Tạo Người dùng" : "Lưu thay đổi"}</>
                )}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
