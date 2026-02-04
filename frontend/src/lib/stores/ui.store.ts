// src/lib/stores/ui.store.ts
/**
 * UI state management using Zustand
 * Manages sidebar collapse state and other UI preferences
 *
 * ✅ PERFORMANCE: Schema versioning prevents stale localStorage data
 * When adding new fields, increment STORAGE_VERSION and update migrate()
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

// ✅ VERSIONING: Increment when UIState shape changes
const STORAGE_VERSION = 1;

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
      version: STORAGE_VERSION,
      migrate: (persistedState, version) => {
        // If version mismatch, reset to defaults
        if (version !== STORAGE_VERSION) {
          return { isSidebarCollapsed: true };
        }
        return persistedState as UIState;
      },
    }
  )
);
