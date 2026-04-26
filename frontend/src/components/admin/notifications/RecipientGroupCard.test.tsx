// RecipientGroupCard.test.tsx — v5 pre-work: internal_only filter coverage
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import RecipientGroupCard from "./RecipientGroupCard";
import type { RecipientGroup } from "./wizard-types";
import type { ChannelInfo, ResolverTypeOption } from "@/types/api.types";

const RESOLVER_OPTIONS: ResolverTypeOption[] = [
  { value: "lead_owner", label: "Officer phụ trách", description: "" },
];

const EXTERNAL_RESOLVER_OPTIONS = [
  { value: "lead_contact", label: "Lead (Zalo)", description: "" },
];

function makeGroup(kind: "internal" | "external"): RecipientGroup {
  return {
    group_key: kind === "internal" ? "group_1" : "ext_1",
    label: "Test",
    recipient_kind: kind,
    recipient_config:
      kind === "internal" ? { resolver_type: "lead_owner", params: {} } : null,
    external_resolver: kind === "external" ? "lead_contact" : null,
    channels: [],
  };
}

const CHANNELS_WITH_INTERNAL_ONLY: ChannelInfo[] = [
  { value: "browser", status: "live", internal_only: false },
  { value: "email", status: "live", internal_only: false },
  { value: "zalo", status: "live", internal_only: false },
  { value: "zalo_bot", status: "live", internal_only: true },
];

const baseProps = {
  index: 0,
  onChange: vi.fn(),
  onRemove: vi.fn(),
  resolverOptions: RESOLVER_OPTIONS,
  externalResolverOptions: EXTERNAL_RESOLVER_OPTIONS,
  browserUsedByOtherGroup: false,
};

describe("RecipientGroupCard — v5 internal_only filter", () => {
  it("internal recipient sees internal_only channels (e.g. zalo_bot)", () => {
    render(
      <RecipientGroupCard
        {...baseProps}
        group={makeGroup("internal")}
        availableChannels={CHANNELS_WITH_INTERNAL_ONLY}
      />,
    );

    // AddChannelBar renders buttons for available channels not yet in the group.
    // Internal recipient should expose every channel including internal_only.
    expect(screen.getByText("Trong ứng dụng")).toBeDefined();
    expect(screen.getByText("Email")).toBeDefined();
    expect(screen.getByText("Zalo")).toBeDefined();
    // v5 Step 23: zalo_bot now has CHANNEL_LABELS["zalo_bot"]="Zalo Bot".
    expect(screen.getByText("Zalo Bot")).toBeDefined();
    expect(screen.queryByText("zalo_bot")).toBeNull();
  });

  it("external recipient hides internal_only channels", () => {
    render(
      <RecipientGroupCard
        {...baseProps}
        group={makeGroup("external")}
        availableChannels={CHANNELS_WITH_INTERNAL_ONLY}
      />,
    );

    // External must hide browser (existing behavior) AND zalo_bot (internal_only).
    expect(screen.queryByText("Trong ứng dụng")).toBeNull();
    expect(screen.queryByText("Zalo Bot")).toBeNull();
    expect(screen.queryByText("zalo_bot")).toBeNull();
    // Public channels remain visible.
    expect(screen.getByText("Email")).toBeDefined();
    expect(screen.getByText("Zalo")).toBeDefined();
  });

  it("external recipient still hides browser when no internal_only flag is set (backward-compat)", () => {
    const legacyChannels: ChannelInfo[] = [
      { value: "browser", status: "live" }, // internal_only undefined
      { value: "email", status: "live" },
      { value: "zalo", status: "live" },
    ];

    render(
      <RecipientGroupCard
        {...baseProps}
        group={makeGroup("external")}
        availableChannels={legacyChannels}
      />,
    );

    expect(screen.queryByText("Trong ứng dụng")).toBeNull();
    expect(screen.getByText("Email")).toBeDefined();
    expect(screen.getByText("Zalo")).toBeDefined();
  });

  it("falls back to DEFAULT_CHANNELS_INFO when availableChannels is undefined", () => {
    // Internal default = browser + email + zalo
    render(
      <RecipientGroupCard
        {...baseProps}
        group={makeGroup("internal")}
      />,
    );

    expect(screen.getByText("Trong ứng dụng")).toBeDefined();
    expect(screen.getByText("Email")).toBeDefined();
    expect(screen.getByText("Zalo")).toBeDefined();
  });
});
