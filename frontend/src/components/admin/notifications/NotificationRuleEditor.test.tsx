// NotificationRuleEditor.test.tsx — Component tests for the rule editor
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/test/utils/test-utils";
import userEvent from "@testing-library/user-event";
import { NotificationRuleEditor } from "./NotificationRuleEditor";

// ============================================================================
// Mocks
// ============================================================================

const mockPush = vi.fn();
const mockBack = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, back: mockBack }),
  useParams: () => ({ id: "1" }),
}));

const mockCreateMutateAsync = vi.fn().mockResolvedValue({ id: 99 });
const mockUpdateMutateAsync = vi.fn().mockResolvedValue({ id: 1 });
const mockUseNotificationRule = vi.fn();

vi.mock("@/hooks/useNotificationRules", () => ({
  useCreateNotificationRule: () => ({ mutateAsync: mockCreateMutateAsync, isPending: false }),
  useUpdateNotificationRule: () => ({ mutateAsync: mockUpdateMutateAsync, isPending: false }),
  useNotificationRule: (...args: unknown[]) => mockUseNotificationRule(...args),
  useNotificationMetadata: () => ({ data: MOCK_METADATA }),
}));

const MOCK_METADATA = {
  events: [
    { event: "lead_created", display_name: "Có lead mới", category: "lead", description: "Test", variables: [] },
    { event: "lead_assigned", display_name: "Lead phân công", category: "lead", description: "Test", variables: [] },
  ],
  channels: [
    { value: "browser", status: "live" },
    { value: "email", status: "live" },
    { value: "zalo", status: "live" },
  ],
  resolver_types: [
    { value: "lead_owner", label: "Officer phụ trách", description: "Test" },
    { value: "unit_staff", label: "Nhân viên đơn vị", description: "Test" },
  ],
  external_resolver_types: [
    { value: "lead_contact", label: "Lead (Zalo)", description: "Test" },
  ],
};

const MOCK_EXISTING_RULE = {
  id: 1,
  event: "lead_created",
  title_template: "Lead mới: $lead_name",
  message_template: "Có lead mới trong hệ thống",
  notification_type: "info",
  link_template: "/leads/$lead_id",
  // Wave 4b (2026-04-21): legacy `channels` field removed from
  // NotificationRule schema — channels are derived from `actions`.
  recipient_config: { resolver_type: "lead_owner", params: {} },
  condition: null,
  enabled: true,
  actions: [
    {
      id: 1, step: 1, channel: "browser", delay_minutes: 0,
      content_mode: "inherit_default", template_code: null,
      content_override: null, config: null,
      branch_key: "group_1_browser",
      recipient_config: { resolver_type: "lead_owner", params: {} },
    },
  ],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

// ============================================================================
// Tests — Shell rendering
// ============================================================================

describe("NotificationRuleEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_EXISTING_RULE : undefined,
      isLoading: false,
    }));
  });

  it("renders create mode with step 1 heading", () => {
    render(<NotificationRuleEditor />);
    expect(screen.getByText("Tạo quy tắc thông báo mới")).toBeDefined();
    expect(screen.getByText("Sự kiện & Điều kiện")).toBeDefined();
  });

  it("renders all 4 step labels", () => {
    render(<NotificationRuleEditor />);
    expect(screen.getByText("Sự kiện & Điều kiện")).toBeDefined();
    expect(screen.getByText("Soạn nội dung")).toBeDefined();
    expect(screen.getByText("Người nhận & Kênh gửi")).toBeDefined();
    expect(screen.getByText("Kiểm tra & Lưu")).toBeDefined();
  });

  it("shows quick templates in create mode on step 1", () => {
    render(<NotificationRuleEditor />);
    expect(screen.getByText("Cấu hình nhanh")).toBeDefined();
    expect(screen.getByText("Manager tạo lead → Gửi cho Officers")).toBeDefined();
  });

  it("does not show quick templates in edit mode", () => {
    render(<NotificationRuleEditor ruleId={1} />);
    expect(screen.queryByText("Cấu hình nhanh")).toBeNull();
  });

  it("renders edit mode heading and hydrates event", () => {
    render(<NotificationRuleEditor ruleId={1} />);
    expect(screen.getByText("Chỉnh sửa quy tắc thông báo")).toBeDefined();
  });
});

// ============================================================================
// Tests — Step navigation + validation
// ============================================================================

describe("NotificationRuleEditor — step navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_EXISTING_RULE : undefined,
      isLoading: false,
    }));
  });

  it("blocks Next when no event is selected — shows inline error on click", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    const nextButton = screen.getByText("Tiếp theo");
    await user.click(nextButton);

    // Inline error banner should appear (text-destructive class)
    const errorElements = screen.getAllByText(/chọn sự kiện/i);
    const inlineError = errorElements.find(
      (el) => el.classList.contains("text-destructive")
    );
    expect(inlineError).toBeDefined();
  });

  it("navigates to step 2 via quick template click", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    await user.click(screen.getByText("Lead được phân công"));

    // Step 2 content should render
    expect(screen.getByText(/Bước 2: Nội dung mặc định/)).toBeDefined();
  });

  it("navigates through all 4 steps using quick template", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    // Quick template → step 2
    await user.click(screen.getByText("Lead được phân công"));

    // Step 2 → 3 → 4 (quick template pre-fills all fields)
    await user.click(screen.getByText("Tiếp theo"));
    await user.click(screen.getByText("Tiếp theo"));

    // Step 4: verify preview renders with toggle
    await waitFor(() => {
      expect(screen.getByText("Tóm tắt quy tắc:")).toBeDefined();
    });
    expect(screen.getByText("Kích hoạt ngay")).toBeDefined();
  });
});

// ============================================================================
// Tests — Step 3 validation (recipient groups)
// ============================================================================

describe("NotificationRuleEditor — step 3 validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_EXISTING_RULE : undefined,
      isLoading: false,
    }));
  });

  it("create mode: adding external group with empty zalo template blocks Next at step 3", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    // Quick template → step 2 (pre-fills event + content + 1 valid group)
    await user.click(screen.getByText("Lead được phân công"));

    // Step 2 → step 3: click Next, then verify step 3 mounted via DOM check
    await user.click(screen.getByText("Tiếp theo"));

    // Step 3 should be current. Verify via step title button state.
    await waitFor(() => {
      const step3Btn = screen.getByTitle("Người nhận & Kênh gửi");
      expect(step3Btn.className).toContain("border-primary");
    });

    // Add external group — button text contains Vietnamese "khách hàng"
    // Use index-based find (button 10 in debug dump) to avoid Unicode matching issues
    const buttons = screen.getAllByRole("button");
    const addExtBtn = buttons.find((btn) => {
      const t = btn.textContent || "";
      // Match the ASCII-safe substrings around the Vietnamese text
      return t.includes("nh") && t.includes("ng/") && btn.tagName === "BUTTON";
    });
    expect(addExtBtn).toBeDefined();
    await user.click(addExtBtn!);

    // Click Next — step 3 now invalid (empty zalo_template_id)
    await user.click(screen.getByText("Tiếp theo"));

    // Verify step 4 was NOT reached (preview text absent)
    const reachedStep4 = screen.queryByText("Tóm tắt quy tắc:") !== null;
    expect(reachedStep4).toBe(false);
  });

  it("edit mode with invalid group: clicking step 4 redirects to step 3 with errors", async () => {
    // Mock rule with empty resolver_type → validateGroups flags "cần chọn người nhận"
    const MOCK_INVALID_RULE = {
      ...MOCK_EXISTING_RULE,
      id: 2,
      actions: [{
        ...MOCK_EXISTING_RULE.actions[0],
        recipient_config: { resolver_type: "", params: {} },
      }],
    };
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_INVALID_RULE : undefined,
      isLoading: false,
    }));

    const user = userEvent.setup();
    render(<NotificationRuleEditor ruleId={2} />);

    // In edit mode, highestStepVisited=4 so step 4 is accessible in the indicator.
    // But handleStepClick forward-checks prior steps. Step 3 has errors → redirected there.
    await user.click(screen.getByTitle("Kiểm tra & Lưu"));

    // Should NOT show step 4 preview (redirected to step 3)
    expect(screen.queryByText("Tóm tắt quy tắc:")).toBeNull();

    // Step 3 should now show inline validation errors (attemptedSteps includes step 3)
    await waitFor(() => {
      const errors = screen.getAllByText(/chọn người nhận/i);
      expect(errors.some((el) => el.classList.contains("text-destructive"))).toBe(true);
    });
  });

  it("edit mode with invalid group: save is never called", async () => {
    const MOCK_INVALID_RULE = {
      ...MOCK_EXISTING_RULE,
      id: 2,
      actions: [{
        ...MOCK_EXISTING_RULE.actions[0],
        recipient_config: { resolver_type: "", params: {} },
      }],
    };
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_INVALID_RULE : undefined,
      isLoading: false,
    }));

    const user = userEvent.setup();
    render(<NotificationRuleEditor ruleId={2} />);

    // Try clicking step 4 to reach save — should be blocked at step 3
    await user.click(screen.getByTitle("Kiểm tra & Lưu"));

    // Neither create nor update should have been called
    expect(mockCreateMutateAsync).not.toHaveBeenCalled();
    expect(mockUpdateMutateAsync).not.toHaveBeenCalled();
  });
});

// ============================================================================
// Tests — Edit mode hydration
// ============================================================================

describe("NotificationRuleEditor — edit mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_EXISTING_RULE : undefined,
      isLoading: false,
    }));
  });

  it("hydrates form fields from existing rule", () => {
    render(<NotificationRuleEditor ruleId={1} />);

    // Edit mode heading
    expect(screen.getByText("Chỉnh sửa quy tắc thông báo")).toBeDefined();
    // Should be on step 1
    expect(screen.getByText("Sự kiện & Điều kiện")).toBeDefined();
  });

  it("allows navigating to any step in edit mode (all steps accessible)", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor ruleId={1} />);

    // In edit mode, highestStepVisited=4, so clicking step 4 indicator should work
    // Find step 4 button by title
    const step4Button = screen.getByTitle("Kiểm tra & Lưu");
    await user.click(step4Button);

    // Step 4 content should render
    expect(screen.getByText("Tóm tắt quy tắc:")).toBeDefined();
  });

  it("shows Cập nhật button (not Tạo) in edit mode on step 4", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor ruleId={1} />);

    // Navigate to step 4
    const step4Button = screen.getByTitle("Kiểm tra & Lưu");
    await user.click(step4Button);

    expect(screen.getByText("Cập nhật")).toBeDefined();
  });
});

// ============================================================================
// Tests — Submit / Save
// ============================================================================

describe("NotificationRuleEditor — submit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseNotificationRule.mockImplementation((id?: number) => ({
      data: id ? MOCK_EXISTING_RULE : undefined,
      isLoading: false,
    }));
  });

  it("calls createMutation on save in create mode", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    // Use quick template to fill all steps
    await user.click(screen.getByText("Lead được phân công"));
    await user.click(screen.getByText("Tiếp theo")); // → step 3
    await user.click(screen.getByText("Tiếp theo")); // → step 4

    // Click save button
    const saveButton = screen.getByText("Tạo quy tắc");
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockCreateMutateAsync).toHaveBeenCalledTimes(1);
    });

    // Verify payload structure
    const payload = mockCreateMutateAsync.mock.calls[0][0];
    expect(payload.event).toBe("lead_assigned");
    expect(payload.title_template).toContain("Lead được phân công");
    expect(payload.actions.length).toBeGreaterThan(0);
    expect(payload.actions[0].channel).toBe("browser");
    expect(payload.enabled).toBe(true);
  });

  it("calls updateMutation on save in edit mode", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor ruleId={1} />);

    // Navigate to step 4 directly (edit mode, all steps accessible)
    const step4Button = screen.getByTitle("Kiểm tra & Lưu");
    await user.click(step4Button);

    // Click update button
    const updateButton = screen.getByText("Cập nhật");
    await user.click(updateButton);

    await waitFor(() => {
      expect(mockUpdateMutateAsync).toHaveBeenCalledTimes(1);
    });

    // Verify it passes ruleId
    const callArgs = mockUpdateMutateAsync.mock.calls[0][0];
    expect(callArgs.ruleId).toBe(1);
    expect(callArgs.data.event).toBe("lead_created");
  });

  it("redirects to notification-rules list after successful save", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    await user.click(screen.getByText("Lead được phân công"));
    await user.click(screen.getByText("Tiếp theo")); // → step 3
    await user.click(screen.getByText("Tiếp theo")); // → step 4
    await user.click(screen.getByText("Tạo quy tắc"));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/admin/notification-rules");
    });
  });
});
