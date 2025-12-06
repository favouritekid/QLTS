// src/app/(dashboard)/profile/_components/ProfileClient.tsx
"use client";

import { useAuth } from "@/hooks/useAuth";
import { EditProfileForm } from "@/components/forms/EditProfileForm";
import type { User } from "@/types/api.types";

interface ProfileClientProps {
  initialUser?: User;
}

export function ProfileClient({ initialUser }: ProfileClientProps) {
  // Use hook with initialData for hydration
  useAuth({ initialData: initialUser });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Hồ Sơ</h1>
        <p className="text-muted-foreground">Quản lý thông tin hồ sơ và cài đặt của bạn.</p>
      </header>

      <EditProfileForm />
    </div>
  );
}
