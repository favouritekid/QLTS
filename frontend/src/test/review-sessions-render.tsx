/**
 * CHỈ cho test GĐ2-B (màn lần xét): QueryClient mang ĐÚNG mặc định của ứng dụng (`src/app/providers.tsx`: `staleTime` / `gcTime`
 * 5 phút, không tự tải lại khi quay lại cửa sổ) — biến thể "bỏ tuỳ chọn ở hook" phải rơi về đúng giá trị production, không về
 * mặc định "không cache" của bộ test khác. `retry: false` để ca lỗi không chờ thử lại.
 */
import type { ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render } from "@testing-library/react"

export function appLikeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 5 * 60 * 1000, gcTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: false },
      mutations: { retry: false },
    },
  })
}

export function renderApp(ui: ReactNode) {
  const queryClient = appLikeQueryClient()
  const utils = render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
  return { queryClient, ...utils }
}
