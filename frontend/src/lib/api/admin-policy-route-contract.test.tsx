/**
 * Hợp đồng route: cụm policy / permission / sync của trang quản trị.
 *
 * Tệp anh em của `admin-role-endpoints.contract.test.tsx` (tệp đó gác gán/thu
 * hồi vai trò). Ở đây gác TÁM thao tác còn lại, tất cả đều từng trỏ vào đường
 * KHÔNG router nào phục vụ — nên chúng hỏng bằng 404/422 câm, không bằng lỗi
 * biên dịch:
 *
 *   1. thêm grouping policy   `/api/admin/grouping-policies`      (thiếu `/roles`)
 *   2. xoá grouping policy    `/api/admin/grouping-policies`      (thiếu `/roles`)
 *   3. lookup who-can-access  GET `/api/admin/policies/who-can-access`
 *   4. simulate               POST `/api/admin/policies/simulate`
 *   5. explain                GET `${role}/explain`               (thiếu `/permissions`)
 *   6. sync status            GET `/api/admin/policies/sync-status`
 *   7. sync users             POST `/api/admin/sync/users`        (thừa `/users`)
 *   8. apply template         body gửi `validate` thay vì `run_validation`
 *
 * Ba tầng, cố ý KHÔNG gộp — vì mỗi tầng một mình đều xanh được trong lúc tầng
 * kia hỏng:
 *
 *   Tầng 1 — GIÁ TRỊ hằng. So chuỗi tuyệt đối với đường đọc từ decorator backend.
 *   Chỉ chứng minh bảng hằng đúng, KHÔNG chứng minh ai dùng nó.
 *
 *   Tầng 2 — LỜI GỌI THẬT. Mock axios rồi đọc `mock.calls`: method nào, URL nào,
 *   tham số nằm ở đối số thứ mấy. Đây là tầng bắt được ca "hằng đúng mà hook vẫn
 *   hardcode chuỗi cũ" — chính hình dạng của lỗi đã vá ở `0b87ac4e`.
 *
 *   Tầng 3 — QUÉT ĐƯỜNG CHẾT. Chạy hết tám consumer trong MỘT ca rồi soi mọi URL
 *   đã phát ra. Tầng này là lưới, không phải neo: nó bắt được cả những đường
 *   không ai nghĩ tới, nhưng khi đỏ thì phải nhìn tầng 2 để biết đỏ vì đâu.
 *
 * Trừ ca quét ở tầng 3, mỗi `it` chỉ vi phạm được MỘT bất biến.
 *
 * ⚠️ `who-can-access` là ca dễ sửa sai nhất: backend đổi sang **POST**
 * (roles.py:1336) nhưng vẫn khai `object`/`action` bằng `Query(...)`. Chuyển
 * chúng vào JSON body sẽ cho một 422 trông hệt như "backend hỏng", nên có hai ca
 * riêng khoá đúng chỗ đặt tham số.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { createTestQueryClient } from "@/test/utils/test-utils";

vi.mock("@/lib/api/client", () => {
  const api = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return { api, apiClient: api, default: api };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

// Import SAU `vi.mock` để mọi consumer nhận bản axios đã mock.
import { api } from "@/lib/api/client";
import { policiesApi } from "@/lib/api/policies";
import {
  useAddGroupingPolicy,
  useApplyTemplate,
  useDeleteGroupingPolicy,
} from "@/hooks/usePolicies";
import { usePermissionExplain } from "@/hooks/usePermissionExplain";
import { TemplatesTab } from "@/components/admin/policies/TemplatesTab";

const PERMISSIONS = API_ENDPOINTS.ADMIN.PERMISSIONS;
const SYNC = API_ENDPOINTS.ADMIN.SYNC;

/** Vai trò mẫu dùng cho mọi hằng dạng HÀM, để chuỗi sinh ra so được tuyệt đối. */
const VAI_TRO_MAU = "manager";

/**
 * Đường THẬT backend đăng ký. Nguồn là DECORATOR + PREFIX, không phải tên hằng:
 *   roles.py:61                APIRouter(prefix="/roles")
 *   sync.py:28                 APIRouter(prefix="/sync")
 *   admin/__init__.py:54       APIRouter(prefix="/admin")
 *   main.py:957                include_router(admin_router, prefix="/api")
 */
const DUONG_THAT = {
  GROUPING: "/api/admin/roles/grouping-policies", // POST roles.py:558 · DELETE roles.py:639
  WHO_CAN_ACCESS: "/api/admin/roles/permissions/who-can-access", // POST roles.py:1336
  SIMULATE: "/api/admin/roles/permissions/simulate", // POST roles.py:1078
  EXPLAIN: `/api/admin/roles/${VAI_TRO_MAU}/permissions/explain`, // GET roles.py:1205
  SYNC_STATUS: "/api/admin/sync/status", // GET  sync.py:31
  SYNC_RUN: "/api/admin/sync", // POST sync.py:53 — `@router.post("")`
  APPLY_TEMPLATE: "/api/admin/roles/templates/apply", // POST roles.py:895
} as const;

/**
 * Đường CHẾT: không router nào trong `app/` phục vụ chúng, và commit này cố ý
 * KHÔNG dựng alias backend để "chữa" — alias là nguồn chuẩn thứ hai cho cùng một
 * hành động và nó che mất chính lỗi này ở lần sau.
 */
const DUONG_CHET = [
  "/api/admin/policies/who-can-access",
  "/api/admin/policies/simulate",
  "/api/admin/grouping-policies",
  "/api/admin/policies/sync-status",
  "/api/admin/sync/users",
  "/api/admin/policies/sync",
  `/api/admin/roles/${VAI_TRO_MAU}/explain`,
] as const;

/**
 * Đi vòng qua `unknown` thay vì `vi.mocked(...)`: `AxiosInstance.get/post/delete`
 * là hàm GENERIC nhiều tham số kiểu, và việc suy `Parameters<>` của chúng phụ
 * thuộc phiên bản axios/vitest. Các ca dưới đây nói về URL và vị trí tham số,
 * nên chúng không nên đỏ vì một bản nâng cấp kiểu.
 */
type GiaMock = {
  mock: { calls: unknown[][] };
  mockResolvedValue: (value: unknown) => GiaMock;
};

function nhuMock(fn: unknown): GiaMock {
  return fn as unknown as GiaMock;
}

function argCuaLoiGoi(fn: unknown, argIndex: number, callIndex = 0): unknown {
  const calls = nhuMock(fn).mock.calls;
  if (calls.length <= callIndex) {
    throw new Error(`Không có lời gọi thứ ${callIndex}; đã ghi nhận ${calls.length}.`);
  }
  return calls[callIndex][argIndex];
}

/**
 * `vitest.config.ts` bật `mockReset` ⇒ mọi implementation bị xoá TRƯỚC mỗi ca.
 * Gọi hàm này ngay đầu thân `it` (chứ không trong `beforeEach`) để không phải
 * phụ thuộc vào thứ tự giữa hook reset nội bộ của vitest và hook của người dùng.
 * Các hàm trong `policiesApi` đọc `response.data`, nên chúng cần một phản hồi
 * thật sự chứ không nuốt được `undefined`.
 */
function chuanBiPhanHoi(): void {
  nhuMock(api.get).mockResolvedValue({ data: {} });
  nhuMock(api.post).mockResolvedValue({ data: {} });
  nhuMock(api.delete).mockResolvedValue({ data: {} });
}

/** Mọi URL (đối số 0) mà axios giả đã nhận, qua cả ba method. */
function moiUrlDaGoi(): string[] {
  const ketQua: string[] = [];
  for (const fn of [api.get, api.post, api.delete]) {
    for (const loiGoi of nhuMock(fn).mock.calls) {
      if (typeof loiGoi[0] === "string") ketQua.push(loiGoi[0]);
    }
  }
  return ketQua;
}

/**
 * Trải `Object.values(<bảng endpoint>)` thành danh sách chuỗi.
 *
 * ⚠️ GỌI cả hằng dạng HÀM (`EXPLAIN`, `ROLE_FEATURES`, `TOGGLE_FEATURE`). Bản
 * quét cũ chỉ lọc `typeof url === "string"` nên hằng hàm lọt lưới hoàn toàn —
 * mà `EXPLAIN` lại đúng là một trong những hằng từng trỏ sai.
 */
function moiChuoiTrongBang(giaTriBang: unknown[]): string[] {
  return giaTriBang.flatMap((giaTri) => {
    if (typeof giaTri === "string") return [giaTri];
    if (typeof giaTri === "function") {
      return [(giaTri as (roleName: string) => string)(VAI_TRO_MAU)];
    }
    return [];
  });
}

function createWrapper() {
  const queryClient = createTestQueryClient();
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = "TestQueryClientWrapper";
  return Wrapper;
}

// ============================================================================
// Tầng 1 — GIÁ TRỊ hằng
// ============================================================================

describe("hợp đồng route policy — hằng số", () => {
  it("GROUPING_POLICIES trỏ đúng /api/admin/roles/grouping-policies", () => {
    expect(PERMISSIONS.GROUPING_POLICIES).toBe(DUONG_THAT.GROUPING);
  });

  it("WHO_CAN_ACCESS trỏ đúng /api/admin/roles/permissions/who-can-access", () => {
    expect(PERMISSIONS.WHO_CAN_ACCESS).toBe(DUONG_THAT.WHO_CAN_ACCESS);
  });

  it("SIMULATE trỏ đúng /api/admin/roles/permissions/simulate", () => {
    expect(PERMISSIONS.SIMULATE).toBe(DUONG_THAT.SIMULATE);
  });

  it("EXPLAIN sinh đường có đoạn /permissions ở giữa", () => {
    expect(PERMISSIONS.EXPLAIN(VAI_TRO_MAU)).toBe(DUONG_THAT.EXPLAIN);
  });

  it("SYNC.STATUS trỏ đúng /api/admin/sync/status", () => {
    expect(SYNC.STATUS).toBe(DUONG_THAT.SYNC_STATUS);
  });

  it("SYNC.RUN đúng bằng /api/admin/sync, KHÔNG có hậu tố /users", () => {
    // `@router.post("")` trên prefix `/sync` (sync.py:53) ⇒ đường đầy đủ không
    // có đoạn nào sau `/sync`. Bản cũ gọi `/api/admin/sync/users`.
    expect(SYNC.RUN).toBe(DUONG_THAT.SYNC_RUN);
  });

  it("mọi hằng PERMISSIONS — kể cả hằng dạng HÀM — nằm trong cụm /api/admin/roles", () => {
    // Cụm này do MỘT router phục vụ. Một hằng rơi ra ngoài `/api/admin/roles` là
    // dấu hiệu nó trỏ vào đường không tồn tại. Ca này cũng chính là thứ giữ cho
    // `SYNC` không bị nhét vào `PERMISSIONS`: `/api/admin/sync` sẽ rơi ra ngoài.
    const ngoaiCum = moiChuoiTrongBang(Object.values(PERMISSIONS)).filter(
      (url) => !url.startsWith("/api/admin/roles")
    );
    expect(ngoaiCum).toEqual([]);
  });

  it("không hằng PERMISSIONS/SYNC nào còn chạm đường chết", () => {
    const chet = new Set<string>(DUONG_CHET);
    const viPham = [
      ...moiChuoiTrongBang(Object.values(PERMISSIONS)),
      ...moiChuoiTrongBang(Object.values(SYNC)),
    ].filter((url) => chet.has(url));
    expect(viPham).toEqual([]);
  });
});

// ============================================================================
// Tầng 2 — LỜI GỌI THẬT (method · URL · vị trí tham số)
// ============================================================================

describe("hợp đồng route policy — consumer thật gọi đường nào", () => {
  it("useAddGroupingPolicy gửi POST tới /api/admin/roles/grouping-policies", async () => {
    chuanBiPhanHoi();
    const { result } = renderHook(() => useAddGroupingPolicy(), { wrapper: createWrapper() });

    result.current.mutate({ subject: "role:support", parent_role: "role:user" });

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.GROUPING);
  });

  it("useDeleteGroupingPolicy gửi DELETE tới /api/admin/roles/grouping-policies", async () => {
    chuanBiPhanHoi();
    const { result } = renderHook(() => useDeleteGroupingPolicy(), { wrapper: createWrapper() });

    result.current.mutate({ subject: "role:support", parent_role: "role:user" });

    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.delete, 0)).toBe(DUONG_THAT.GROUPING);
  });

  it("payload xoá grouping đi trong `config.data`, không phải body vị trí 2", async () => {
    // Axios `delete(url, config)`: truyền payload sai chỗ thì backend nhận body
    // rỗng và trả 422 — một lỗi im lặng ở tầng client.
    chuanBiPhanHoi();
    const { result } = renderHook(() => useDeleteGroupingPolicy(), { wrapper: createWrapper() });

    result.current.mutate({ subject: "role:support", parent_role: "role:user" });

    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.delete, 1)).toEqual({
      data: { subject: "role:support", parent_role: "role:user" },
    });
  });

  it("lookupPermissions dùng POST — không phải GET", async () => {
    chuanBiPhanHoi();

    await policiesApi.lookupPermissions("/api/leads", "GET");

    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.get).not.toHaveBeenCalled();
  });

  it("lookupPermissions gửi tới /api/admin/roles/permissions/who-can-access", async () => {
    chuanBiPhanHoi();

    await policiesApi.lookupPermissions("/api/leads", "GET");

    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.WHO_CAN_ACCESS);
  });

  it("lookupPermissions đặt object/action ở CONFIG thứ ba (`params`)", async () => {
    // Backend khai hai tham số này bằng `Query(...)` (roles.py:1339-1340), nên
    // dù method là POST chúng vẫn phải nằm trong query string.
    chuanBiPhanHoi();

    await policiesApi.lookupPermissions("/api/leads", "GET");

    expect(argCuaLoiGoi(api.post, 2)).toEqual({
      params: { object: "/api/leads", action: "GET" },
    });
  });

  it("lookupPermissions KHÔNG gói object/action vào JSON body", async () => {
    // Bất biến riêng: gói vào body thì FastAPI vẫn thấy THIẾU query bắt buộc và
    // trả 422 — trông y hệt "backend hỏng", nên phải có ca chỉ nói về body.
    chuanBiPhanHoi();

    await policiesApi.lookupPermissions("/api/leads", "GET");

    expect(argCuaLoiGoi(api.post, 1)).toBeUndefined();
  });

  it("simulatePermission gửi POST tới /api/admin/roles/permissions/simulate", async () => {
    chuanBiPhanHoi();

    await policiesApi.simulatePermission({
      subject: "role:manager",
      object: "/api/leads",
      action: "GET",
    });

    expect(api.post).toHaveBeenCalledTimes(1);
    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.SIMULATE);
  });

  it("simulatePermission gửi subject/object/action trong JSON body", async () => {
    // Ngược với lookup: `PermissionSimulateRequest` là body schema (roles.py:1080).
    chuanBiPhanHoi();

    await policiesApi.simulatePermission({
      subject: "role:manager",
      object: "/api/leads",
      action: "GET",
    });

    expect(argCuaLoiGoi(api.post, 1)).toEqual({
      subject: "role:manager",
      object: "/api/leads",
      action: "GET",
    });
  });

  it("usePermissionExplain gửi GET tới đường có đoạn /permissions", async () => {
    chuanBiPhanHoi();
    renderHook(() => usePermissionExplain(VAI_TRO_MAU), { wrapper: createWrapper() });

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.get, 0)).toBe(DUONG_THAT.EXPLAIN);
  });

  it("getSyncStatus gửi GET tới /api/admin/sync/status", async () => {
    chuanBiPhanHoi();

    await policiesApi.getSyncStatus();

    expect(api.get).toHaveBeenCalledTimes(1);
    expect(argCuaLoiGoi(api.get, 0)).toBe(DUONG_THAT.SYNC_STATUS);
  });

  it("syncUsers gửi POST tới /api/admin/sync (không có /users)", async () => {
    chuanBiPhanHoi();

    await policiesApi.syncUsers([7, 9]);

    expect(api.post).toHaveBeenCalledTimes(1);
    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.SYNC_RUN);
  });

  it("syncUsers gửi body { user_ids }, giữ nguyên null khi đồng bộ tất cả", async () => {
    chuanBiPhanHoi();

    await policiesApi.syncUsers(null);

    expect(argCuaLoiGoi(api.post, 1)).toEqual({ user_ids: null });
  });

  it("useApplyTemplate gửi POST tới /api/admin/roles/templates/apply", async () => {
    chuanBiPhanHoi();
    const { result } = renderHook(() => useApplyTemplate(), { wrapper: createWrapper() });

    result.current.mutate({
      template_id: "core_officer",
      role: "role:custom",
      run_validation: true,
    });

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.APPLY_TEMPLATE);
  });

  it("policiesApi KHÔNG còn phơi ra `syncPolicies` — endpoint đó không tồn tại", () => {
    // Hàm cũ trỏ `POST /api/admin/policies/sync`, không router nào phục vụ và 0
    // nơi gọi. Giữ lại một hàm chết chỉ chờ ai đó "dùng thử" rồi tưởng backend hỏng.
    expect(Object.keys(policiesApi)).not.toContain("syncPolicies");
  });
});

// ============================================================================
// Tầng 2b — TemplatesTab: cờ kiểm tra phải mang ĐÚNG TÊN backend nghe được
// ============================================================================

const MAU_TEMPLATE = {
  id: "core_officer",
  display_name: "Core Officer",
  description: "Bộ quyền chuẩn cho chuyên viên tuyển sinh",
  category: "core" as const,
  policies: [{ subject: "role:officer", object: "/api/leads", action: "GET" }],
};

/**
 * Dựng TemplatesTab rồi đi trọn đường người dùng: mở hộp thoại → nhập vai trò →
 * bấm Apply. Cố ý dùng `fireEvent` chứ không `userEvent`: Radix Dialog đặt
 * `pointer-events: none` lên `document.body` khi modal mở, và `userEvent` v14
 * ném lỗi "element has pointer-events: none" ở đúng cú bấm cuối.
 */
async function moPhongApDungTemplate(): Promise<void> {
  nhuMock(api.get).mockResolvedValue({ data: { templates: [MAU_TEMPLATE] } });
  nhuMock(api.post).mockResolvedValue({
    data: { added: 1, removed: 0, skipped: 0, blocked: 0, errors: [], warnings: [] },
  });

  render(<TemplatesTab />, { wrapper: createWrapper() });

  fireEvent.click(await screen.findByRole("button", { name: "Apply Template" }));

  const hopThoai = await screen.findByRole("dialog");
  fireEvent.change(within(hopThoai).getByLabelText("Target Role"), {
    target: { value: "custom_role" },
  });
  fireEvent.click(within(hopThoai).getByRole("button", { name: "Apply" }));

  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
}

describe("TemplatesTab — cờ kiểm tra gửi kèm khi áp template", () => {
  it("gửi tới /api/admin/roles/templates/apply", async () => {
    await moPhongApDungTemplate();
    expect(argCuaLoiGoi(api.post, 0)).toBe(DUONG_THAT.APPLY_TEMPLATE);
  });

  it("body mang `run_validation: true`", async () => {
    // `TemplateApplicationRequest.run_validation` — schemas/permissions.py:137.
    await moPhongApDungTemplate();
    const body = argCuaLoiGoi(api.post, 1) as Record<string, unknown>;
    expect(body.run_validation).toBe(true);
  });

  it("body KHÔNG còn khoá `validate`", async () => {
    // Bất biến riêng, và là bất biến QUAN TRỌNG hơn: Pydantic mặc định BỎ QUA
    // khoá lạ, nên `validate` không hề bị từ chối — nó bị nuốt IM LẶNG và server
    // vẫn chạy với default `True`. Một ca chỉ kiểm `run_validation` sẽ vẫn xanh
    // khi ai đó gửi kèm CẢ HAI khoá, che mất đúng lỗi này.
    await moPhongApDungTemplate();
    const body = argCuaLoiGoi(api.post, 1) as Record<string, unknown>;
    expect(Object.keys(body)).not.toContain("validate");
  });
});

// ============================================================================
// Tầng 3 — LƯỚI: chạy hết tám consumer, soi mọi URL phát ra
// ============================================================================

describe("hợp đồng route policy — không consumer nào còn chạm đường chết", () => {
  it("tám thao tác phát ra 0 URL nằm trong danh sách đường chết", async () => {
    chuanBiPhanHoi();
    const wrapper = createWrapper();

    // (1)(2) grouping — thêm và xoá
    const them = renderHook(() => useAddGroupingPolicy(), { wrapper });
    them.result.current.mutate({ subject: "role:support", parent_role: "role:user" });
    await waitFor(() => expect(api.post).toHaveBeenCalled());

    const xoa = renderHook(() => useDeleteGroupingPolicy(), { wrapper });
    xoa.result.current.mutate({ subject: "role:support", parent_role: "role:user" });
    await waitFor(() => expect(api.delete).toHaveBeenCalled());

    // (3)(4)(6)(7) các hàm API phẳng
    await policiesApi.lookupPermissions("/api/leads", "GET");
    await policiesApi.simulatePermission({
      subject: "role:manager",
      object: "/api/leads",
      action: "GET",
    });
    await policiesApi.getSyncStatus();
    await policiesApi.syncUsers(null);

    // (5) explain — chờ theo SỐ LỜI GỌI TĂNG THÊM, không phải
    // `expect(api.get).toHaveBeenCalled()`: `getSyncStatus` ở trên đã gọi
    // `api.get` rồi, nên phép chờ kiểu ấy xanh NGAY trong khi explain còn chưa
    // kịp phát request ⇒ lưới quét thiếu đúng một consumer mà không ai biết.
    // Chờ theo số lần (chứ không theo URL đúng) là cố ý: nếu explain trôi sang
    // đường chết thì ca này vẫn phải đỏ ở phép lọc cuối, kèm URL sai in ra.
    const soGetTruocExplain = nhuMock(api.get).mock.calls.length;
    renderHook(() => usePermissionExplain(VAI_TRO_MAU), { wrapper });
    await waitFor(() =>
      expect(nhuMock(api.get).mock.calls.length).toBe(soGetTruocExplain + 1)
    );

    // (8) apply template — cùng lý do: lúc này đã có 4 lời gọi POST trước đó.
    const soPostTruocTemplate = nhuMock(api.post).mock.calls.length;
    const apDung = renderHook(() => useApplyTemplate(), { wrapper });
    apDung.result.current.mutate({
      template_id: "core_officer",
      role: "role:custom",
      run_validation: true,
    });
    await waitFor(() =>
      expect(nhuMock(api.post).mock.calls.length).toBe(soPostTruocTemplate + 1)
    );

    const chet = new Set<string>(DUONG_CHET);
    expect(moiUrlDaGoi().filter((url) => chet.has(url))).toEqual([]);
  });
});
