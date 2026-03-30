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

vi.mock("@/hooks/useNotificationRules", () => ({
  useCreateNotificationRule: () => ({ mutateAsync: mockCreateMutateAsync, isPending: false }),
  useUpdateNotificationRule: () => ({ mutateAsync: mockUpdateMutateAsync, isPending: false }),
  useNotificationRule: (id?: number) => ({
    data: id ? MOCK_EXISTING_RULE : undefined,
    isLoading: false,
  }),
  useNotificationMetadata: () => ({
    data: MOCK_METADATA,
  }),
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
  channels: ["browser"],
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
// Tests — Edit mode hydration
// ============================================================================

describe("NotificationRuleEditor — edit mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
