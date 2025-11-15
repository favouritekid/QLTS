// src/components/ui/use-toast.ts
/**
 * Toast Hook Wrapper - Compatible with sonner
 *
 * This hook provides a compatibility layer for components that use
 * the standard useToast() pattern, while using sonner under the hood.
 */
import { toast as sonnerToast } from "sonner";

export interface ToastProps {
  title?: string;
  description?: string;
  variant?: "default" | "destructive";
  duration?: number;
}

export function useToast() {
  return {
    toast: ({ title, description, variant, duration }: ToastProps) => {
      const message = title || "";
      const desc = description || "";
      const fullMessage = desc ? `${message}\n${desc}` : message;

      if (variant === "destructive") {
        sonnerToast.error(fullMessage, { duration });
      } else {
        sonnerToast.success(fullMessage, { duration });
      }
    },
  };
}

// Re-export toast for direct usage
export { toast } from "sonner";
