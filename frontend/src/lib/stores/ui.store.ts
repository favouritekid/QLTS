// src/lib/stores/ui.store.ts
/**
 * UI state management using Zustand
 * Manages sidebar collapse state and other UI preferences
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UIState {
  isSidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      isSidebarCollapsed: true, // Default to collapsed/hidden for mobile-first safety

      setSidebarCollapsed: (collapsed: boolean) => {
        set({ isSidebarCollapsed: collapsed });
      },

      toggleSidebar: () => {
        set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed }));
      },
    }),
    {
      name: "ui-storage", // localStorage key
    }
  )
);
