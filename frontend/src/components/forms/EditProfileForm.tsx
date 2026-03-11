// src/components/forms/EditProfileForm.tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import { Camera, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";
import type { UserUpdateProfile } from "@/types/api.types";
import { getAvatarUrl } from "@/lib/utils";

// Zod schema cho form validation
const editProfileSchema = z.object({
  full_name: z.string().max(120, "Họ tên không được vượt quá 120 ký tự").optional(),
  phone_number: z
    .string()
    .max(20, "Số điện thoại không được vượt quá 20 ký tự")
    .regex(/^[0-9+\-\s()]*$/, "Số điện thoại chỉ được chứa số, +, -, khoảng trắng và dấu ngoặc")
    .optional()
    .or(z.literal("")),
  email: z
    .string()
    .email("Định dạng email không hợp lệ")
    .min(1, "Email là bắt buộc"),
  avatar: z.instanceof(File).optional(),
});

type EditProfileFormValues = z.infer<typeof editProfileSchema>;

export function EditProfileForm() {
  const { user, updateProfile, isUpdatingProfile } = useAuth();
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Initialize form with current user data
  const form = useForm<EditProfileFormValues>({
    resolver: zodResolver(editProfileSchema),
    defaultValues: {
      full_name: user?.full_name || "",
      phone_number: user?.phone_number || "",
      email: user?.email || "",
    },
  });

  // F6: Warn user khi navigate away với form dirty (browser-level)
  const isDirty = form.formState.isDirty;
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  // FIX 8: Sync form when user data changes (e.g., after refetch)
  const { reset } = form;

  useEffect(() => {
    if (user) {
      reset({
        full_name: user.full_name || "",
        phone_number: user.phone_number || "",
        email: user.email || "",
      });
    }
  }, [user?.id, user?.full_name, user?.phone_number, user?.email, reset]);

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

  // Handle form submission
  function onSubmit(values: EditProfileFormValues) {
    const updateData: UserUpdateProfile = {
      full_name: values.full_name || null,
      phone_number: values.phone_number || null,
      email: values.email,
    };

    // Only include avatar if a new one was selected
    if (values.avatar) {
      updateData.avatar = values.avatar;
    }

    updateProfile(updateData);
  }

  // Handle avatar click to open file picker
  const handleAvatarClick = () => {
    fileInputRef.current?.click();
  };

  if (!user) {
    return null;
  }

  // If user is uploading new avatar, show preview
  // Otherwise show current avatar from server (converted to absolute URL)
  const displayAvatarUrl = avatarPreview || getAvatarUrl(user.avatar_url);
  const avatarFallback = user.username.slice(0, 2).toUpperCase();

  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>Sửa Hồ Sơ</CardTitle>
        <CardDescription>
          Cập nhật thông tin hồ sơ và ảnh đại diện của bạn. Thay đổi sẽ được lưu khi bạn nhấn Lưu Thay Đổi.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
            {/* Avatar Section */}
            <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6">
              <div className="relative">
                <Avatar className="h-20 w-20 sm:h-24 sm:w-24">
                  <AvatarImage src={displayAvatarUrl} alt={user.username} />
                  <AvatarFallback className="text-xl sm:text-2xl">{avatarFallback}</AvatarFallback>
                </Avatar>
                <button
                  type="button"
                  onClick={handleAvatarClick}
                  className="bg-primary text-primary-foreground hover:bg-primary/90 absolute bottom-0 right-0 rounded-full p-2 shadow-md transition-colors"
                  disabled={isUpdatingProfile}
                  aria-label="Tải ảnh đại diện mới"
                >
                  <Camera className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-1 text-center sm:text-left">
                <p className="text-sm font-medium">Ảnh Đại Diện</p>
                <p className="text-muted-foreground text-xs">
                  Nhấn vào biểu tượng máy ảnh để tải ảnh đại diện mới. JPG, PNG hoặc GIF. Tối đa 5MB.
                </p>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleAvatarChange}
                  className="hidden"
                  disabled={isUpdatingProfile}
                />
                {form.formState.errors.avatar && (
                  <p className="text-destructive text-xs">{form.formState.errors.avatar.message}</p>
                )}
              </div>
            </div>

            {/* Full Name Field */}
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Họ và Tên</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Nhập họ và tên của bạn"
                      autoComplete="name"
                      disabled={isUpdatingProfile}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Email Field */}
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input
                      type="email"
                      placeholder="your.email@example.com"
                      autoComplete="email"
                      disabled={isUpdatingProfile}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Phone Number Field */}
            <FormField
              control={form.control}
              name="phone_number"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Số Điện Thoại</FormLabel>
                  <FormControl>
                    <Input
                      type="tel"
                      placeholder="+1 (555) 123-4567"
                      autoComplete="tel"
                      disabled={isUpdatingProfile}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Username (Read-only) */}
            <div className="space-y-2">
              <Label className="text-muted-foreground">Tên đăng nhập</Label>
              <Input value={user.username} disabled className="bg-muted cursor-not-allowed" />
              <p className="text-muted-foreground text-xs">Tên đăng nhập không thể thay đổi</p>
            </div>

            {/* Role (Read-only) */}
            <div className="space-y-2">
              <Label className="text-muted-foreground">Vai trò</Label>
              <Input
                value={user.role} // architecture-allow serialization
                disabled
                className="bg-muted cursor-not-allowed capitalize"
              />
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3 pt-4">
              <Button type="submit" disabled={isUpdatingProfile}>
                {isUpdatingProfile ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Đang lưu…
                  </>
                ) : (
                  "Lưu Thay Đổi"
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  form.reset();
                  setAvatarPreview(null);
                }}
                disabled={isUpdatingProfile}
              >
                Đặt lại
              </Button>
            </div>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
