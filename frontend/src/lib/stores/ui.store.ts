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

  /**
   * Monotonic counter bumped whenever a global "close all mobile overlays"
   * request fires (e.g. tapping a MobileBottomNav tab). Pages that own a
   * mobile drawer/sheet (Radix modal — which makes the bottom nav itself
   * un-tappable) subscribe to this nonce and close their overlay on change.
   * Runtime-only signal: excluded from persistence via `partialize`.
   */
  mobileOverlayCloseNonce: number;
  requestCloseMobileOverlays: () => void;
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

      mobileOverlayCloseNonce: 0,
      requestCloseMobileOverlays: () => {
        set((state) => ({ mobileOverlayCloseNonce: state.mobileOverlayCloseNonce + 1 }));
      },
    }),
    {
      name: "ui-storage", // localStorage key
      version: STORAGE_VERSION,
      // Only persist the sidebar preference. The overlay-close nonce is a
      // transient runtime signal and must never be written to localStorage
      // (a stale persisted value would fire a spurious close on rehydrate).
      partialize: (state) => ({ isSidebarCollapsed: state.isSidebarCollapsed }),
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
