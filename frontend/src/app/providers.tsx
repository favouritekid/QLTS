// src/app/providers.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { Toaster } from "sonner";
import { AxiosError } from "axios"; // <<< THÊM IMPORT NÀY

// RQ Devtools đã tắt: nút floating của nó nằm góc dưới-phải, đè bong bóng
// "Trợ lý nhắc hẹn" (AppointmentAssistant). Cần debug query thì bật lại tạm.

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

        // Invalidate critical data — only refetch queries that are currently mounted
        queryClient.invalidateQueries({ queryKey: ["admin"], refetchType: 'active' });
        queryClient.invalidateQueries({ queryKey: ["users"], refetchType: 'active' });
        queryClient.invalidateQueries({ queryKey: ["leads"], refetchType: 'active' });
        queryClient.invalidateQueries({ queryKey: ["organization"], refetchType: 'active' });
        queryClient.invalidateQueries({ queryKey: ["notifications"], refetchType: 'active' });

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
          // F2: nút "Hoàn tác" trên toast không bấm được khi toast render lúc
          // Radix AlertDialog modal còn mở (Radix set pointer-events:none lên
          // body). pointer-events-auto trả lại khả năng bấm cho toast.
          className: "pointer-events-auto",
          style: {
            maxWidth: '400px', // Giới hạn chiều rộng toast
          },
        }}
      />
    </QueryClientProvider>
  );
}
