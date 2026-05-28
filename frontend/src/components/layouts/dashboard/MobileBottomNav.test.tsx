// @vitest-environment jsdom
/**
 * MobileBottomNav — overlay-hide contract.
 *
 * The bar (z-[60]) must hide while a dialog/sheet overlay is open (else it
 * paints over the overlay's lowest content). The signal is Radix's
 * `data-scroll-locked` on <body> — BUT that attribute is ALSO set by
 * <Select> (listbox) and <DropdownMenu> (menu), which don't occlude the bar.
 * These tests pin that the bar:
 *   - shows by default,
 *   - hides for a real dialog/sheet (scroll-locked + role=dialog open),
 *   - STAYS for a Select/Dropdown (scroll-locked, NO role=dialog) — the
 *     regression guard for the over-broad `data-scroll-locked` signal.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import { Database } from "lucide-react";
import { MobileBottomNav } from "./MobileBottomNav";

vi.mock("next/navigation", () => ({ usePathname: () => "/leads" }));
vi.mock("@/hooks/useNotifications", () => ({
  useNotifications: () => ({ data: { unread_count: 0 } }),
}));
vi.mock("@/hooks/useAppNavigation", () => ({
  useAppNavigation: () => ({
    navigation: [{ items: [{ href: "/leads", label: "Lead", icon: Database }] }],
  }),
}));
vi.mock("@/lib/stores/ui.store", () => ({
  useUIStore: (selector: (s: unknown) => unknown) =>
    selector({ isSidebarCollapsed: true, requestCloseMobileOverlays: () => {} }),
}));

function openOverlay(role: "dialog" | "listbox") {
  document.body.setAttribute("data-scroll-locked", "");
  const node = document.createElement("div");
  node.setAttribute("role", role);
  node.setAttribute("data-state", "open");
  node.setAttribute("data-test-overlay", "");
  document.body.appendChild(node);
}

afterEach(() => {
  // Unmount FIRST so the body MutationObserver is disconnected before we clear
  // `data-scroll-locked` — otherwise removing it would fire a setState on the
  // still-mounted component outside act() (noisy warning).
  cleanup();
  document.body.removeAttribute("data-scroll-locked");
  document.querySelectorAll("[data-test-overlay]").forEach((n) => n.remove());
});

describe("MobileBottomNav — overlay-hide contract", () => {
  it("renders the bar by default (no overlay)", () => {
    render(<MobileBottomNav />);
    expect(screen.queryByRole("navigation")).not.toBeNull();
  });

  it("hides while a dialog/sheet is open (scroll-locked + role=dialog)", async () => {
    // DOM set before render → the mount effect's initial sync() flips the
    // hidden state; await act() flushes that passive-effect update (React 19
    // runs effects after commit) so the re-render to null is inside act().
    openOverlay("dialog");
    await act(async () => {
      render(<MobileBottomNav />);
    });
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("STAYS visible while only a Select/Dropdown is open (scroll-locked, no role=dialog)", () => {
    // Radix Select/DropdownMenu lock body scroll but render role=listbox/menu,
    // not role=dialog — the bar must NOT hide for them.
    openOverlay("listbox");
    render(<MobileBottomNav />);
    expect(screen.queryByRole("navigation")).not.toBeNull();
  });
});
