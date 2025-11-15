// src/types/layout.types.ts
import { type LucideIcon } from "lucide-react";

export type NavigationLink = {
  label: string;
  href: string;
  icon?: LucideIcon;
  children?: NavigationLink[];
  badge?: string | number;
  matchPath?: string[]; // Additional paths that should activate this item
  excludePaths?: string[]; // Paths to exclude from parent active state
};
