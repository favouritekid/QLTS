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
    .min(3, "Username must be at least 3 characters")
    .max(64, "Username must be less than 64 characters")
    .regex(/^[a-zA-Z0-9_-]+$/, "Username can only contain letters, numbers, hyphens, and underscores"),
  email: z.string().email("Invalid email address"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .regex(/[A-Z]/, "Password must contain at least one uppercase letter")
    .regex(/[a-z]/, "Password must contain at least one lowercase letter")
    .regex(/\d/, "Password must contain at least one number")
    .regex(/[@$!%*?&]/, "Password must contain at least one special character"),
  full_name: z.string().max(120, "Full name must be less than 120 characters").optional(),
  role: z.string().min(1, "Role is required").default("user"),
  status: z.enum(["active", "pending", "banned"]).default("active"),
  avatar: z.instanceof(File).optional(),
});

const editUserSchema = z.object({
  full_name: z.string().max(120, "Full name must be less than 120 characters").optional(),
  email: z.string().email("Invalid email address"),
  phone_number: z.string().max(20, "Phone number must be less than 20 characters").optional(),
  role: z.string().min(1, "Role is required"),
  status: z.enum(["active", "pending", "banned"]),
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
          message: "Please select a valid image file",
        });
        return;
      }

      // Validate file size (max 5MB)
      if (file.size > 5 * 1024 * 1024) {
        form.setError("avatar", {
          type: "manual",
          message: "Image size must be less than 5MB",
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
                >
                  <Camera className="h-3 w-3" />
                </button>
              </div>
              <div className="flex-1 space-y-1">
                <p className="text-sm font-medium">Ảnh đại diện</p>
                <p className="text-muted-foreground text-xs">
                  JPG, PNG hoặc GIF. Tối đa 5MB.
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
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                    {String((form.formState.errors.avatar as any)?.message || "Invalid file")}
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
                      <Input placeholder="nguyenvana" disabled={isPending} {...field} />
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
                    <Input placeholder="Nguyễn Văn A" disabled={isPending} {...field} />
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
                    defaultValue={field.value}
                    disabled={isPending || rolesLoading}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder={rolesLoading ? "Đang tải vai trò..." : "Chọn vai trò"} />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {rolesLoading ? (
                        <SelectItem value="" disabled>
                          Đang tải vai trò...
                        </SelectItem>
                      ) : availableRoles.length === 0 ? (
                        <SelectItem value="" disabled>
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

            {/* Status */}
            <FormField
              control={form.control}
              name="status"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Trạng thái *</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
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
                    {isCreate ? "Đang tạo..." : "Đang lưu..."}
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
