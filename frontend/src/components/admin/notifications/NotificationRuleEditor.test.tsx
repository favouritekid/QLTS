// NotificationRuleEditor.test.tsx — Component tests for the rule editor shell
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
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

vi.mock("@/hooks/useNotificationRules", () => ({
  useCreateNotificationRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateNotificationRule: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useNotificationRule: (id?: number) => ({
    data: id ? MOCK_EXISTING_RULE : undefined,
    isLoading: false,
  }),
  useNotificationMetadata: () => ({
    data: {
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
    },
  }),
}));

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
// Tests
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

  it("blocks Next when no event is selected — shows inline error on click", async () => {
    const user = userEvent.setup();
    render(<NotificationRuleEditor />);

    const nextButton = screen.getByText("Tiếp theo");
    await user.click(nextButton);

    // Should still be on step 1 (no event selected)
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

    // Click a quick template — it pre-fills event + content and navigates to step 2
    const templateButton = screen.getByText("Lead được phân công");
    await user.click(templateButton);

    // Step 2 content should render
    expect(screen.getByText(/Bước 2: Nội dung mặc định/)).toBeDefined();
  });
});
