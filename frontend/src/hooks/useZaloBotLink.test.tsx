/**
 * useZaloBotLink hook tests — v5 Step 21.
 *
 * Pin three contracts that are easy to drift on:
 *   - UNLINK is POST (NOT DELETE) — backend treats unlink as a state
 *     mutation that flips zalo_bot_enabled, not a resource deletion.
 *   - useZaloBotLinkStatus stops polling once `is_linked` flips true.
 *   - generate / unlink invalidate the status query so the UI refetches.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";

import { createTestQueryClient } from "@/test/utils/test-utils";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import {
  useGenerateLinkCode,
  useUnlinkZaloBot,
  useZaloBotLinkStatus,
  zaloBotKeys,
} from "./useZaloBotLink";

vi.mock("@/lib/api/client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

// vi.mocked() can't see through the module-level type because `api` is
// typed as the real Axios instance — cast each method to the Mock
// surface so the mock helpers (mockResolvedValueOnce, etc.) compile.
const mockedApi = {
  get: api.get as unknown as Mock,
  post: api.post as unknown as Mock,
  delete: api.delete as unknown as Mock,
  put: api.put as unknown as Mock,
  patch: api.patch as unknown as Mock,
};

function makeWrapper(client = createTestQueryClient()) {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { wrapper, client };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("API_ENDPOINTS.ZALO_BOT contract", () => {
  it("UNLINK is POST endpoint (not DELETE)", () => {
    expect(API_ENDPOINTS.ZALO_BOT.UNLINK).toBe("/api/zalo-bot/unlink");
    expect(API_ENDPOINTS.ZALO_BOT.LINK_CODE).toBe("/api/zalo-bot/link-code");
    expect(API_ENDPOINTS.ZALO_BOT.LINK_STATUS).toBe("/api/zalo-bot/link-status");
  });
});

describe("useZaloBotLinkStatus", () => {
  it("fetches status from LINK_STATUS endpoint", async () => {
    mockedApi.get.mockResolvedValueOnce({
      data: { is_linked: false, display_name: null, linked_at: null },
    });
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useZaloBotLinkStatus(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedApi.get).toHaveBeenCalledWith(API_ENDPOINTS.ZALO_BOT.LINK_STATUS);
    expect(result.current.data?.is_linked).toBe(false);
  });

  it("returns linked payload from server", async () => {
    mockedApi.get.mockResolvedValueOnce({
      data: {
        is_linked: true,
        display_name: "Officer A",
        linked_at: "2026-04-26T10:00:00+00:00",
      },
    });
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useZaloBotLinkStatus(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.is_linked).toBe(true);
    expect(result.current.data?.display_name).toBe("Officer A");
  });
});

describe("useGenerateLinkCode", () => {
  it("POSTs to LINK_CODE and invalidates status cache", async () => {
    mockedApi.post.mockResolvedValueOnce({
      data: {
        code: "ABC123",
        expires_in_seconds: 600,
        instructions: "Mở Zalo, tìm bot QLTS, gửi: /lienket ABC123",
      },
    });

    const { wrapper, client } = makeWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useGenerateLinkCode(), { wrapper });
    await act(async () => {
      const res = await result.current.mutateAsync();
      expect(res.code).toBe("ABC123");
      expect(res.expires_in_seconds).toBe(600);
    });

    expect(mockedApi.post).toHaveBeenCalledWith(API_ENDPOINTS.ZALO_BOT.LINK_CODE);
    // Hook must invalidate the status query so the polling refetch picks
    // up the new server state.
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: zaloBotKeys.status() });
  });
});

describe("useUnlinkZaloBot", () => {
  it("POSTs (not DELETE) to UNLINK", async () => {
    mockedApi.post.mockResolvedValueOnce({
      data: { unlinked: true, message: "Đã huỷ liên kết." },
    });

    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useUnlinkZaloBot(), { wrapper });

    await act(async () => {
      const res = await result.current.mutateAsync();
      expect(res.unlinked).toBe(true);
    });

    // Critical: the backend uses POST. A DELETE here would 405.
    expect(mockedApi.post).toHaveBeenCalledWith(API_ENDPOINTS.ZALO_BOT.UNLINK);
    expect(mockedApi.delete).not.toHaveBeenCalled();
  });

  it("invalidates both status and notification preference caches on success", async () => {
    mockedApi.post.mockResolvedValueOnce({
      data: { unlinked: true, message: "Đã huỷ liên kết." },
    });

    const { wrapper, client } = makeWrapper();
    const invalidateSpy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useUnlinkZaloBot(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync();
    });

    // Two distinct scopes invalidated: zalo bot link status (for the
    // polling query) AND the broader notification-preferences scope so
    // the settings UI re-reads ``zalo_bot_enabled=false``.
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: zaloBotKeys.status() });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["notificationPreferences"],
    });
  });
});
