// src/components/layouts/dashboard/Header.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@/test/utils/test-utils";
import { Header } from "./Header";

// ── Mocks ──────────────────────────────────────────────────────────

// useAuth - controls user role for TopNav permission tests
const mockUser = { id: 1, username: "test", email: "t@t.com", role: "officer" };
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ user: mockUser })),
}));
import { useAuth } from "@/hooks/useAuth";
const mockUseAuth = vi.mocked(useAuth);

// useCommandPalette
vi.mock("@/hooks/useCommandPalette", () => ({
  useCommandPalette: vi.fn(() => ({
    isOpen: false,
    open: vi.fn(),
    close: vi.fn(),
    toggle: vi.fn(),
    query: "",
    setQuery: vi.fn(),
    filteredItems: [],
    executeCommand: vi.fn(),
  })),
}));

// useUIStore
vi.mock("@/lib/stores/ui.store", () => ({
  useUIStore: vi.fn(() => ({
    isSidebarCollapsed: false,
    toggleSidebar: vi.fn(),
  })),
}));

// SecurityBanner
vi.mock("@/components/layouts/SecurityBanner", () => ({
  useShouldShowSecurityBanner: vi.fn(() => false),
  SECURITY_BANNER_HEIGHT: 40,
}));

// ThemeToggle & NotificationDropdown - lightweight stubs
vi.mock("@/components/ui/theme-toggle", () => ({
  ThemeToggle: () => <div data-testid="theme-toggle" />,
}));
vi.mock("@/components/notifications/NotificationDropdown", () => ({
  NotificationDropdown: () => <div data-testid="notification-dropdown" />,
}));
vi.mock("@/components/leads/AppointmentReminder", () => ({
  AppointmentReminder: () => <div data-testid="appointment-reminder" />,
}));

// ── Helpers ────────────────────────────────────────────────────────

function setUserRole(role: string) {
  mockUseAuth.mockReturnValue({
    user: { ...mockUser, role },
  } as ReturnType<typeof useAuth>);
}

function setPlatform(platform: string) {
  Object.defineProperty(navigator, "platform", {
    value: platform,
    writable: true,
    configurable: true,
  });
}

// ── Tests ──────────────────────────────────────────────────────────

describe("Header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuth.mockReturnValue({
      user: { ...mockUser, role: "officer" },
    } as ReturnType<typeof useAuth>);
    setPlatform("Win32");
  });

  // ── Fix 1: Text revert ────────────────────────────────────────

  describe("Dashboard label", () => {
    it('should display "Bảng điều khiển" without personalized text', () => {
      render(<Header />);
      expect(screen.getByText("Bảng điều khiển")).toBeInTheDocument();
      expect(screen.queryByText(/của Hà/)).not.toBeInTheDocument();
    });
  });

  // ── Fix 3: Permission-based admin nav ─────────────────────────

  describe("TopNav admin link visibility", () => {
    it("should always show Dashboard and Lead links", () => {
      render(<Header />);
      expect(screen.getByText("Bảng điều khiển")).toBeInTheDocument();
      expect(screen.getByText("Lead")).toBeInTheDocument();
    });

    it('should hide "Người dùng" link for officer role', () => {
      setUserRole("officer");
      render(<Header />);
      expect(screen.queryByText("Người dùng")).not.toBeInTheDocument();
    });

    it('should hide "Người dùng" link for user role', () => {
      setUserRole("user");
      render(<Header />);
      expect(screen.queryByText("Người dùng")).not.toBeInTheDocument();
    });

    it('should show "Người dùng" link for admin role', () => {
      setUserRole("admin");
      render(<Header />);
      expect(screen.getByText("Người dùng")).toBeInTheDocument();
    });

    it('should show "Người dùng" link for manager role', () => {
      setUserRole("manager");
      render(<Header />);
      expect(screen.getByText("Người dùng")).toBeInTheDocument();
    });

    it('should hide "Người dùng" link when user is null', () => {
      mockUseAuth.mockReturnValue({
        user: null,
      } as ReturnType<typeof useAuth>);
      render(<Header />);
      expect(screen.queryByText("Người dùng")).not.toBeInTheDocument();
    });
  });

  // ── Fix 4: OS-aware keyboard shortcut ─────────────────────────

  describe("Keyboard shortcut display", () => {
    it('should show "Ctrl+" on Windows', async () => {
      setPlatform("Win32");
      render(<Header />);

      // useEffect runs after render — flush it
      await act(async () => {});

      expect(screen.getByText("Ctrl+")).toBeInTheDocument();
      expect(screen.queryByText("⌘")).not.toBeInTheDocument();
    });

    it('should show "Ctrl+" on Linux', async () => {
      setPlatform("Linux x86_64");
      render(<Header />);
      await act(async () => {});

      expect(screen.getByText("Ctrl+")).toBeInTheDocument();
    });

    it('should show "⌘" on macOS', async () => {
      setPlatform("MacIntel");
      render(<Header />);
      await act(async () => {});

      expect(screen.getByText("⌘")).toBeInTheDocument();
      expect(screen.queryByText("Ctrl+")).not.toBeInTheDocument();
    });

    it('should show "⌘" on iPad', async () => {
      setPlatform("iPad");
      render(<Header />);
      await act(async () => {});

      expect(screen.getByText("⌘")).toBeInTheDocument();
    });
  });

  // ── Fix 5: No scale classes ───────────────────────────────────

  describe("Search button styling", () => {
    it("should not have scale transform classes", () => {
      render(<Header />);
      const searchButton = screen.getByRole("button", {
        name: "Tìm kiếm trang và thao tác",
      });

      expect(searchButton.className).not.toMatch(/scale-/);
    });

    it("should have hover:shadow-md for visual feedback", () => {
      render(<Header />);
      const searchButton = screen.getByRole("button", {
        name: "Tìm kiếm trang và thao tác",
      });

      expect(searchButton.className).toContain("hover:shadow-md");
    });
  });

  // ── General structure ─────────────────────────────────────────

  describe("Structure", () => {
    it("should render sidebar toggle button with aria-label", () => {
      render(<Header />);
      expect(
        screen.getByRole("button", { name: "Bật/tắt thanh bên" })
      ).toBeInTheDocument();
    });

    it("should render theme toggle and notification dropdown", () => {
      render(<Header />);
      expect(screen.getByTestId("theme-toggle")).toBeInTheDocument();
      expect(screen.getByTestId("notification-dropdown")).toBeInTheDocument();
    });
  });
});
