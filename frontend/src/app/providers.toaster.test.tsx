/**
 * Thông báo nhiều dòng phải HIỆN nhiều dòng.
 *
 * Hook `useImportLeads` dựng `description` gồm vài dòng nối bằng "\n" để người
 * nhập biết dòng nào hỏng. Nhưng sonner không đặt quy tắc `white-space` nào, nên
 * mặc định của trình duyệt (`normal`) gộp mọi "\n" thành dấu cách — ba thông báo
 * pydantic thô nối lại thành một đoạn văn chạy dài trong hộp rộng 400px, tự tắt
 * sau 12 giây, số dòng lẫn hết vào nhau.
 *
 * Test này đo WIRING chứ không đo cấu hình: nó dựng `Providers` thật, bắn một
 * toast thật, rồi đọc lớp CSS trên ĐÚNG nút DOM mà sonner sinh ra. Khẳng định
 * `toastOptions.classNames.description === "..."` trong tệp nguồn thì không
 * chứng minh được gì — chỉ cần sonner đổi tên khoá là lớp đó rơi vào hư không mà
 * phép so vẫn xanh.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { Providers } from "./providers";

// Providers nạp socket client kiểu lazy trong useEffect — không liên quan gì ở đây.
vi.mock("@/lib/socket/client", () => ({
  socketService: { onReconnect: vi.fn() },
}));

describe("Providers / Toaster", () => {
  it("giu nguyen xuong dong trong description cua toast", async () => {
    render(
      <Providers>
        <div />
      </Providers>,
    );

    toast.warning("Nhập được 2, bỏ qua 8 dòng", {
      description: "Dòng 3: email không hợp lệ\nDòng 4: thiếu họ tên",
    });

    const moTa = await screen.findByText(/Dòng 3: email không hợp lệ/);

    await waitFor(() =>
      expect(moTa.className).toContain("whitespace-pre-line"),
    );
  });
});
