// src/app/(dashboard)/profile/_components/ProfileClient.tsx
"use client";

import { useAuth } from "@/hooks/useAuth";
import { EditProfileForm } from "@/components/forms/EditProfileForm";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import type { User } from "@/types/api.types";

interface ProfileClientProps {
  initialUser?: User;
}

export function ProfileClient({ initialUser }: ProfileClientProps) {
  // Use hook with initialData for hydration
  useAuth({ initialData: initialUser });

  return (
    <PageContainer maxWidth="md">
      <PageHeader
        title="Hồ Sơ"
        description="Quản lý thông tin hồ sơ và cài đặt của bạn."
      />
      <EditProfileForm />
    </PageContainer>
  );
}
