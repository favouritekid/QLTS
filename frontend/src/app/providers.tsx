// src/app/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useState, useEffect } from "react";
import { Toaster } from "sonner";
import { AxiosError } from "axios"; // <<< THÊM IMPORT NÀY

// ✅ PERF: Lazy-load DevTools - chỉ dùng trong development
const ReactQueryDevtools = dynamic(
  () => import("@tanstack/react-query-devtools").then(m => ({ default: m.ReactQueryDevtools })),
  { ssr: false }
);

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 60 * 1000,
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
  // ✅ PERF: Lazy-load socketService - chỉ import khi cần, giảm initial bundle
  useEffect(() => {
    import("@/lib/socket/client").then(({ socketService }) => {
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
    });

    // Cleanup not needed - callback persists for app lifetime
    return () => {
      // No-op: socketService is singleton and callback should persist
    };
  }, [queryClient]);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster 
        position="top-right" 
        richColors 
        closeButton 
        expand={false}
        duration={8000}        // Tăng thời gian hiển thị: 8 giây (mặc định 4s)
        visibleToasts={3}      // Tối đa 3 toast hiển thị cùng lúc
        gap={8}                // Khoảng cách giữa các toast (px)
        toastOptions={{
          style: {
            maxWidth: '400px', // Giới hạn chiều rộng toast
          },
        }}
      />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
