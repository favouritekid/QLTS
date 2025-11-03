// src/app/(auth)/reset-password/page.tsx
import { ResetPasswordForm } from "@/components/forms/ResetPasswordForm";
import { Metadata } from "next";
import { Suspense } from "react"; // <<< THÊM Suspense

export const metadata: Metadata = {
  title: "Reset Password",
  description: "Set a new password for your account",
};

// Component wrapper để sử dụng Suspense
function ResetPasswordContent() {
  return <ResetPasswordForm />;
}

export default function ResetPasswordPage() {
  // <<< BỌC ResetPasswordContent trong Suspense >>>
  // Vì ResetPasswordForm dùng useSearchParams, nó cần Suspense bao bọc
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <ResetPasswordContent />
    </Suspense>
  );
}
