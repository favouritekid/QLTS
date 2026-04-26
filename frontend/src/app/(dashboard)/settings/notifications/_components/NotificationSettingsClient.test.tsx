/**
 * NotificationSettingsClient — v5 Step 22 settings UI tests.
 *
 * The screen pulls four hooks; we mock all of them to drive only the
 * Zalo Bot section. Coverage focuses on the contract:
 *   - "Generate" calls the hook and renders the code.
 *   - Polling stops once is_linked flips true (UI swaps to "linked").
 *   - "Unlink" calls the hook.
 *   - The per-group zalo_bot toggle is disabled when zalo_bot_enabled
 *     is false (i.e. the user has not linked yet) — and re-enabling
 *     never sends zalo_bot_enabled in an update payload.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/test/utils/test-utils";
import userEvent from "@testing-library/user-event";

import { NotificationSettingsClient } from "./NotificationSettingsClient";

// ───────────────────────────────────────────────────────────────────
// Hook mocks
// ───────────────────────────────────────────────────────────────────

const mockGenerate = vi.fn();
const mockUnlink = vi.fn();
const mockUpdatePref = vi.fn();
const mockUpdateGroupPref = vi.fn();
// Phase 6a fix: capture invalidateQueries calls so we can assert that
// the link-transition effect invalidates the preferences scope.
const mockInvalidateQueries = vi.fn();

vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<
    typeof import("@tanstack/react-query")
  >("@tanstack/react-query");
  return {
    ...actual,
    useQueryClient: () => ({
      invalidateQueries: mockInvalidateQueries,
      // The settings UI only calls invalidateQueries on this client; if
      // it ever needs more methods we'll fail loudly with `undefined is
      // not a function` and add them deliberately.
    }),
  };
});

const linkStatusReturn: { current: { is_linked: boolean; display_name: string | null; linked_at: string | null } | undefined } = {
  current: { is_linked: false, display_name: null, linked_at: null },
};

const preferencesReturn: { current: any } = {
  current: {
    id: 1,
    user_id: 1,
    email_enabled: true,
    sound_enabled: true,
    browser_enabled: true,
    zalo_bot_enabled: false,
    email_digest: "instant",
    type_preferences: null,
    quiet_hours_enabled: false,
    quiet_hours_start: null,
    quiet_hours_end: null,
  },
};

vi.mock("@/hooks/useNotificationPreferences", () => ({
  // The settings UI imports ``notificationPreferenceKeys.all`` to scope
  // its cache invalidation. Mirror the real shape (a tagged tuple, not
  // a plain string) so the assertion in tests matches what the hook
  // module actually exports.
  notificationPreferenceKeys: {
    all: ["notificationPreferences"],
    detail: () => ["notificationPreferences", "detail"],
    eventGroups: () => ["notificationPreferences", "eventGroups"],
  },
  useNotificationPreferences: () => ({ data: preferencesReturn.current }),
  useUpdateNotificationPreferences: () => ({
    mutateAsync: mockUpdatePref,
    isPending: false,
  }),
  useEventGroupPreferences: () => ({
    data: {
      groups: [
        {
          id: "lead",
          name_en: "Lead",
          name_vi: "Lead",
          description_en: "",
          description_vi: "",
        },
      ],
      preferences: { lead: { browser: true, email: true, zalo_bot: false, sms: false } },
    },
  }),
  useUpdateEventGroupPreference: () => ({
    mutateAsync: mockUpdateGroupPref,
    isPending: false,
  }),
}));

vi.mock("@/hooks/useZaloBotLink", () => ({
  useZaloBotLinkStatus: () => ({ data: linkStatusReturn.current }),
  useGenerateLinkCode: () => ({ mutateAsync: mockGenerate, isPending: false }),
  useUnlinkZaloBot: () => ({ mutateAsync: mockUnlink, isPending: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockInvalidateQueries.mockClear();
  // Reset state between tests.
  linkStatusReturn.current = { is_linked: false, display_name: null, linked_at: null };
  preferencesReturn.current = {
    ...preferencesReturn.current,
    zalo_bot_enabled: false,
  };
});

describe("Zalo Bot section", () => {
  it("shows generate button when not linked, calls hook, then renders code", async () => {
    mockGenerate.mockResolvedValueOnce({
      code: "ABC123",
      expires_in_seconds: 600,
      instructions: "Mở Zalo, tìm bot QLTS, gửi: /lienkiet ABC123",
    });

    render(<NotificationSettingsClient />);

    const button = screen.getByTestId("zalo-bot-generate");
    expect(button).toBeDefined();

    await userEvent.click(button);

    await waitFor(() => {
      expect(mockGenerate).toHaveBeenCalled();
    });

    const codeNode = await screen.findByTestId("zalo-bot-code");
    expect(codeNode.textContent).toBe("ABC123");
    expect(screen.getByText(/Mở Zalo/)).toBeDefined();
    // TTL hint is rendered (10 phút).
    expect(screen.getByText(/10 phút/)).toBeDefined();
  });

  it("renders linked state and unlink button calls hook", async () => {
    linkStatusReturn.current = {
      is_linked: true,
      display_name: "Officer A",
      linked_at: "2026-04-26T10:00:00+00:00",
    };
    mockUnlink.mockResolvedValueOnce({ unlinked: true, message: "Đã huỷ liên kết." });

    render(<NotificationSettingsClient />);

    expect(screen.getByText("Đã liên kết")).toBeDefined();
    expect(screen.getByText("Officer A")).toBeDefined();

    await userEvent.click(screen.getByTestId("zalo-bot-unlink"));
    await waitFor(() => expect(mockUnlink).toHaveBeenCalled());
  });

  it("hides the generated code once status flips linked (poll stop)", async () => {
    // Initial render: generate code so the pending box is visible.
    mockGenerate.mockResolvedValueOnce({
      code: "ABC123",
      expires_in_seconds: 600,
      instructions: "instr",
    });
    const { rerender } = render(<NotificationSettingsClient />);
    await userEvent.click(screen.getByTestId("zalo-bot-generate"));
    await screen.findByTestId("zalo-bot-code");

    // Simulate the polling query observing is_linked=true.
    linkStatusReturn.current = {
      is_linked: true,
      display_name: "Officer A",
      linked_at: "2026-04-26T10:00:00+00:00",
    };
    rerender(<NotificationSettingsClient />);

    await waitFor(() => {
      expect(screen.queryByTestId("zalo-bot-code")).toBeNull();
    });
    expect(screen.getByText("Đã liên kết")).toBeDefined();
  });

  it("Phase 6a: invalidates notificationPreferences cache when link flips active", async () => {
    // Generate code first so pendingCode is set — that's the precondition
    // the effect looks at when distinguishing "user just linked" from
    // "page loaded already linked".
    mockGenerate.mockResolvedValueOnce({
      code: "ABC123",
      expires_in_seconds: 600,
      instructions: "instr",
    });
    const { rerender } = render(<NotificationSettingsClient />);
    await userEvent.click(screen.getByTestId("zalo-bot-generate"));
    await screen.findByTestId("zalo-bot-code");

    // Webhook fires server-side → polling sees is_linked=true.
    linkStatusReturn.current = {
      is_linked: true,
      display_name: "Officer A",
      linked_at: "2026-04-26T10:00:00+00:00",
    };
    rerender(<NotificationSettingsClient />);

    // The fix: settings UI must invalidate the preferences scope so the
    // per-group zalo_bot toggle observes ``zalo_bot_enabled=true`` on
    // the next render — without this users had to hard-refresh.
    await waitFor(() => {
      expect(mockInvalidateQueries).toHaveBeenCalledWith({
        queryKey: ["notificationPreferences"],
      });
    });
  });
});

describe("Per-group zalo_bot column", () => {
  it("disables zalo_bot toggle when zalo_bot_enabled is false", () => {
    preferencesReturn.current = {
      ...preferencesReturn.current,
      zalo_bot_enabled: false,
    };
    render(<NotificationSettingsClient />);
    const toggle = screen.getByTestId("zalo-bot-toggle-lead") as HTMLButtonElement;
    expect(toggle.getAttribute("data-state")).toBe("unchecked");
    // Radix Switch sets aria-disabled / disabled attribute.
    expect(toggle.hasAttribute("disabled") || toggle.getAttribute("aria-disabled") === "true").toBe(true);
  });

  it("enables zalo_bot toggle when zalo_bot_enabled is true", () => {
    preferencesReturn.current = {
      ...preferencesReturn.current,
      zalo_bot_enabled: true,
    };
    render(<NotificationSettingsClient />);
    const toggle = screen.getByTestId("zalo-bot-toggle-lead") as HTMLButtonElement;
    expect(toggle.hasAttribute("disabled")).toBe(false);
  });

  it("save general settings never includes zalo_bot_enabled in payload", async () => {
    mockUpdatePref.mockResolvedValueOnce({});
    render(<NotificationSettingsClient />);

    await userEvent.click(screen.getByRole("button", { name: /Lưu/ }));

    await waitFor(() => expect(mockUpdatePref).toHaveBeenCalled());
    const payload = mockUpdatePref.mock.calls[0][0];
    expect(payload).not.toHaveProperty("zalo_bot_enabled");
  });
});
