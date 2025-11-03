// src/app/(auth)/login/page.tsx
import { LoginForm } from "@/components/forms/LoginForm";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Login",
  description: "Login to your account",
};

export default function LoginPage() {
  return <LoginForm />;
}
