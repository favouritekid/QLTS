// src/app/(auth)/forgot-password/page.tsx
import { ForgotPasswordForm } from "@/components/forms/ForgotPasswordForm";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Forgot Password",
  description: "Request a password reset link",
};

export default function ForgotPasswordPage() {
  return <ForgotPasswordForm />;
}
