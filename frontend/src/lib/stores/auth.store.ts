// src/lib/stores/auth.store.ts
/**
 * Authentication state management using Zustand
 *
 * ✅ SECURITY FIX: Removed localStorage token storage
 *
 * Tokens are now managed via httpOnly cookies (set by backend):
 * - access_token: Used for API requests (httpOnly, path="/")
 * - refresh_token: Used for token refresh (httpOnly, path="/api")
 *
 * This store only manages user info for UI purposes.
 * Authentication state is derived from cookie presence (verified by middleware).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/types/api.types";

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  setAuth: (user: User) => void;
  setUser: (user: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,

      setAuth: (user: User) => {
        // ✅ SECURITY FIX: No longer store token in localStorage
        // Token is managed via httpOnly cookies by backend

        set({
          user,
          isAuthenticated: true,
        });
      },

      setUser: (user: User) => {
        // Update only user info
        set({ user });
      },

      logout: () => {
        // ✅ SECURITY FIX: No need to clear localStorage
        // Cookies are cleared by backend /logout endpoint

        // Clear security banner dismiss state so it shows again on next login
        if (typeof window !== "undefined") {
          localStorage.removeItem("security_banner_dismissed_until");
        }

        set({
          user: null,
          isAuthenticated: false,
        });
      },
    }),
    {
      name: "auth-storage", // localStorage key (only stores user info now)
      partialize: (state) => ({
        // ✅ SECURITY FIX: Only persist user info (not token)
        user: state.user,
        // isAuthenticated will be re-derived from cookies on page load
      }),
      onRehydrateStorage: () => (state) => {
        // ✅ SECURITY FIX: Check if cookies exist to set isAuthenticated
        // This is a client-side hint only; real auth is verified by middleware
        if (state && typeof window !== "undefined") {
          // Check if access_token cookie exists (non-httpOnly check not possible)
          // We'll rely on API calls to validate auth state
          state.isAuthenticated = !!state.user;
        }
      },
    }
  )
);
