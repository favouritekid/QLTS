// src/components/admin/UserDialog.tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { useForm } from "react-hook-form";
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
import type { User } from "@/types/api.types";

// Validation schemas
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
  role: z.enum(["user", "admin", "manager", "officer"]).default("user"),
  status: z.enum(["active", "pending", "banned"]).default("active"),
  avatar: z.instanceof(File).optional(),
});

const editUserSchema = z.object({
  full_name: z.string().max(120, "Full name must be less than 120 characters").optional(),
  email: z.string().email("Invalid email address"),
  phone_number: z.string().max(20, "Phone number must be less than 20 characters").optional(),
  role: z.enum(["user", "admin", "manager", "officer"]),
  status: z.enum(["active", "pending", "banned"]),
  avatar: z.instanceof(File).optional(),
});

type CreateUserFormValues = z.infer<typeof createUserSchema>;
type EditUserFormValues = z.infer<typeof editUserSchema>;

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

  const isCreate = mode === "create";
  const isEdit = mode === "edit";

  // Form setup - use conditional type based on mode
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const form = useForm<any>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(isCreate ? createUserSchema : editUserSchema) as any,
    defaultValues: isEdit && user
      ? {
          full_name: user.full_name || "",
          email: user.email,
          phone_number: user.phone_number || "",
          role: user.role,
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

  // Reset form when dialog opens or user changes
  useEffect(() => {
    if (!open) return;

    if (isEdit && user) {
      form.reset({
        full_name: user.full_name || "",
        email: user.email,
        phone_number: user.phone_number || "",
        role: user.role,
        status: user.status,
      });
    } else if (isCreate) {
      form.reset({
        username: "",
        email: "",
        password: "",
        full_name: "",
        role: "user" as const,
        status: "active" as const,
      });
    }
  }, [open, user, isEdit, isCreate, form]);

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

  // Handle dialog close
  const handleDialogClose = (open: boolean) => {
    onOpenChange(open);
    if (!open) {
      // Reset state when dialog closes
      setAvatarPreview(null);
      setPasswordValue("");
    }
  };

  // Handle form submission
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function onSubmit(values: any) {
    try {
      if (isCreate) {
        await createUserMutation.mutateAsync(values as CreateUserFormValues);
      } else if (user) {
        await updateUserMutation.mutateAsync(values as EditUserFormValues);
      }
      handleDialogClose(false);
      form.reset();
    } catch {
      // Error handling is done in the mutation hooks
    }
  }

  const displayAvatarUrl = avatarPreview || (user?.avatar_url ?? "");
  const avatarFallback = isEdit && user
    ? user.username.slice(0, 2).toUpperCase()
    : "?";

  const isPending = createUserMutation.isPending || updateUserMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleDialogClose}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>{isCreate ? "Create New User" : "Edit User"}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Add a new user to the system. All fields marked with * are required."
              : "Update user information. Leave avatar empty to keep current image."}
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
                <p className="text-sm font-medium">Profile Picture</p>
                <p className="text-muted-foreground text-xs">
                  JPG, PNG or GIF. Max size 5MB.
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
                    <FormLabel>Username *</FormLabel>
                    <FormControl>
                      <Input placeholder="johndoe" disabled={isPending} {...field} />
                    </FormControl>
                    <FormDescription>
                      Must be unique. Can only contain letters, numbers, hyphens, and underscores.
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
                  <FormLabel>Full Name</FormLabel>
                  <FormControl>
                    <Input placeholder="John Doe" disabled={isPending} {...field} />
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
                    <FormLabel>Phone Number</FormLabel>
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
                    <FormLabel>Password *</FormLabel>
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
                  <FormLabel>Role *</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a role" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="user">User</SelectItem>
                      <SelectItem value="officer">Officer</SelectItem>
                      <SelectItem value="manager">Manager</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Determines what the user can access in the system.
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
                  <FormLabel>Status *</FormLabel>
                  <Select
                    onValueChange={field.onChange}
                    defaultValue={field.value}
                    disabled={isPending}
                  >
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select status" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="active">Active</SelectItem>
                      <SelectItem value="pending">Pending</SelectItem>
                      <SelectItem value="banned">Banned</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    Active users can log in. Banned users are blocked.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleDialogClose(false)}
                disabled={isPending}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {isCreate ? "Creating..." : "Saving..."}
                  </>
                ) : (
                  <>{isCreate ? "Create User" : "Save Changes"}</>
                )}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
