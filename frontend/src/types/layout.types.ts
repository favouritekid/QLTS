// src/types/layout.types.ts
import { type LucideIcon } from "lucide-react";

export type NavigationLink = {
  label: string;
  href: string;
  icon?: LucideIcon;
  children?: NavigationLink[];
  badge?: string | number;
};
