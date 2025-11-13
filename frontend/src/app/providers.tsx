// src/app/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, useEffect } from "react";
import { Toaster } from "sonner";
import { AxiosError } from "axios"; // <<< THÊM IMPORT NÀY
import { socketService } from "@/lib/socket/client"; // ✅ PRIORITY 3: Import socket service

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            gcTime: 5 * 60 * 1000,
            refetchOnWindowFocus: false,
            refetchOnReconnect: true,
            // <<< SỬA Ở ĐÂY: Thêm kiểu AxiosError cho error >>>
            retry: (failureCount, error: AxiosError | Error | unknown) => {
              // Check if it's an AxiosError with a response
              if (error instanceof AxiosError && error.response) {
                if (error.response.status >= 400 && error.response.status < 500) {
                  return false; // Don't retry client errors
                }
              }
              // Default retry logic for other errors or server errors
              return failureCount < 3;
            },
            // <<< KẾT THÚC SỬA >>>
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  // ✅ PRIORITY 3 FIX (Deep Dive Audit): Register socket reconnect handler
  // Invalidates critical queries when socket reconnects to prevent stale data
  useEffect(() => {
    socketService.onReconnect(() => {
      console.log("[Providers] 🔄 Socket reconnected - Invalidating critical queries...");

      // Invalidate all critical data that may have changed during disconnect
      // These queries have staleTime: Infinity via SocketHandler, so they need manual invalidation
      queryClient.invalidateQueries({ queryKey: ["admin"] }); // Current user + permissions
      queryClient.invalidateQueries({ queryKey: ["users"] }); // User management
      queryClient.invalidateQueries({ queryKey: ["leads"] }); // Leads data
      queryClient.invalidateQueries({ queryKey: ["organization"] }); // Organization tree
      queryClient.invalidateQueries({ queryKey: ["notifications"] }); // Notifications

      console.log("[Providers] ✅ Cache invalidation triggered - React Query will refetch data");
    });

    // Cleanup not needed - callback persists for app lifetime
    return () => {
      // No-op: socketService is singleton and callback should persist
    };
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster position="top-right" richColors closeButton expand={false} />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
