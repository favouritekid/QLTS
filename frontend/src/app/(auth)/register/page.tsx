// src/app/(auth)/register/page.tsx
import { RegisterForm } from "@/components/forms/RegisterForm";
import { Metadata } from "next";

export const metadata: Metadata = {
  title: "Register",
  description: "Create a new account",
};

export default function RegisterPage() {
  return <RegisterForm />;
}
