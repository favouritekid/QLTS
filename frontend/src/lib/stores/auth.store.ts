// src/lib/stores/auth.store.ts
/**
 * Authentication state management using Zustand
 * Persists token and user info to localStorage
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/types/api.types";

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  setAuth: (user: User, token: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,

      setAuth: (user: User, token: string) => {
        // Store token in localStorage for axios interceptor
        if (typeof window !== "undefined") {
          localStorage.setItem("access_token", token);
        }

        set({
          user,
          token,
          isAuthenticated: true,
        });
      },

      logout: () => {
        // Clear token from localStorage
        if (typeof window !== "undefined") {
          localStorage.removeItem("access_token");
        }

        set({
          user: null,
          token: null,
          isAuthenticated: false,
        });
      },
    }),
    {
      name: "auth-storage", // localStorage key
      partialize: (state) => ({
        // Only persist user and token (not isAuthenticated)
        user: state.user,
        token: state.token,
      }),
      onRehydrateStorage: () => (state) => {
        // After rehydration, sync token to localStorage
        if (state?.token && typeof window !== "undefined") {
          localStorage.setItem("access_token", state.token);
          // Update isAuthenticated based on token existence
          state.isAuthenticated = !!state.token;
        }
      },
    }
  )
);
