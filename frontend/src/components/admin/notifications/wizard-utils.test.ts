// wizard-utils.test.ts — Unit tests for wizard data mapping, validation, and hydration
import { describe, it, expect } from "vitest";
import type { NotificationRule } from "@/types/api.types";
import type { RecipientGroup, WizardDefaultContent, WizardTrigger } from "./wizard-types";
import {
  mapToAPI,
  hydrateFromAPI,
  validateGroups,
  validateAllSteps,
  flattenStepErrors,
  validateStep1,
  validateStep2,
  canSave,
  createInternalGroup,
  createExternalGroup,
  resetGroupCounter,
  resolveFieldAlias,
  OPERATOR_ALIAS_MAP,
} from "./wizard-utils";

// ============================================================================
// Fixtures
// ============================================================================

const DEFAULT_CONTENT: WizardDefaultContent = {
  title_template: "Test title: $lead_name",
  message_template: "Test message body",
  notification_type: "info",
};

const DEFAULT_TRIGGER: WizardTrigger = {
  event: "lead_created",
  condition: null,
  enabled: true,
};

function makeInternalGroup(overrides?: Partial<RecipientGroup>): RecipientGroup {
  return {
    group_key: "group_1",
    label: "Officer phụ trách lead",
    recipient_kind: "internal",
    recipient_config: { resolver_type: "lead_owner", params: {} },
    external_resolver: null,
    channels: [
      {
        channel: "browser",
        delay_minutes: 0,
        content_mode: "inherit_default",
        template_code: null,
        content_override: null,
        config: null,
      },
    ],
    ...overrides,
  };
}

function makeExternalGroup(overrides?: Partial<RecipientGroup>): RecipientGroup {
  return {
    group_key: "ext_1",
    label: "Lead (qua Zalo/SMS)",
    recipient_kind: "external",
    recipient_config: null,
    external_resolver: "lead_contact",
    channels: [
      {
        channel: "zalo",
        delay_minutes: 0,
        content_mode: "channel_native",
        template_code: null,
        content_override: null,
        config: { zalo_template_id: "ZNS_001", zalo_template_data: {} },
      },
    ],
    ...overrides,
  };
}

function makeAction(overrides?: Record<string, unknown>) {
  return {
    id: 1, step: 1, channel: "browser", delay_minutes: 0,
    content_mode: "inherit_default", template_code: null,
    content_override: null, config: null, branch_key: "group_1_browser",
    recipient_config: { resolver_type: "lead_owner", params: {} },
    rule_id: 1, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as NotificationRule["actions"][0];
}

function makeRule(overrides?: Partial<NotificationRule>): NotificationRule {
  return {
    id: 1,
    event: "lead_created",
    title_template: "Test title",
    message_template: "Test message",
    notification_type: "info",
    link_template: "/leads/$lead_id",
    channels: ["browser"],
    recipient_config: { resolver_type: "lead_owner", params: {} },
    condition: null,
    enabled: true,
    actions: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as NotificationRule;
}

// ============================================================================
// mapToAPI
// ============================================================================

describe("mapToAPI", () => {
  it("maps a single internal group with browser channel", () => {
    const result = mapToAPI([makeInternalGroup()], DEFAULT_CONTENT, DEFAULT_TRIGGER);

    expect(result.event).toBe("lead_created");
    expect(result.enabled).toBe(true);
    expect(result.title_template).toBe("Test title: $lead_name");
    // Wave 4b: top-level `channels` removed — assert via actions only.
    expect(result.actions).toHaveLength(1);
    expect(result.actions![0].channel).toBe("browser");
    expect(result.actions![0].step).toBe(1);
    expect(result.actions![0].recipient_config).toEqual({ resolver_type: "lead_owner", params: {} });
    expect(result.actions![0].branch_key).toBe("group_1_browser");
  });

  it("maps an external group — resolver goes in config, not recipient_config", () => {
    const result = mapToAPI([makeExternalGroup()], DEFAULT_CONTENT, DEFAULT_TRIGGER);

    expect(result.actions).toHaveLength(1);
    const action = result.actions![0];
    expect(action.recipient_config).toBeNull();
    expect(action.content_mode).toBe("channel_native");
    expect(action.config).toMatchObject({ external_resolver: "lead_contact" });
  });

  it("maps mixed internal + external groups with correct step numbering", () => {
    const groups = [
      makeInternalGroup({
        channels: [
          { channel: "browser", delay_minutes: 0, content_mode: "inherit_default", template_code: null, content_override: null, config: null },
          { channel: "email", delay_minutes: 5, content_mode: "inherit_default", template_code: null, content_override: null, config: null },
        ],
      }),
      makeExternalGroup(),
    ];
    const result = mapToAPI(groups, DEFAULT_CONTENT, DEFAULT_TRIGGER);

    expect(result.actions).toHaveLength(3);
    expect(result.actions!.map((a) => a.step)).toEqual([1, 2, 3]);
    // Wave 4b: top-level `channels` removed — assert via actions only.
    expect(result.actions!.map((a) => a.channel)).toEqual(["browser", "email", "zalo"]);
    // First internal group sets rule-level recipient_config
    expect(result.recipient_config).toEqual({ resolver_type: "lead_owner", params: {} });
  });

  it("maps inline_override content correctly", () => {
    const group = makeInternalGroup({
      channels: [{
        channel: "email",
        delay_minutes: 0,
        content_mode: "inline_override",
        template_code: null,
        content_override: { title_template: "Custom title", message_template: "Custom msg" },
        config: null,
      }],
    });
    const result = mapToAPI([group], DEFAULT_CONTENT, DEFAULT_TRIGGER);

    expect(result.actions![0].content_mode).toBe("inline_override");
    expect(result.actions![0].content_override).toEqual({
      title_template: "Custom title",
      message_template: "Custom msg",
    });
  });

  it("falls back to lead_owner when no internal groups exist", () => {
    const result = mapToAPI([makeExternalGroup()], DEFAULT_CONTENT, DEFAULT_TRIGGER);
    expect(result.recipient_config).toEqual({ resolver_type: "lead_owner", params: {} });
  });

  it("preserves condition in output", () => {
    const trigger = { ...DEFAULT_TRIGGER, condition: { field: "actor.role", operator: "eq", value: "manager" } };
    const result = mapToAPI([makeInternalGroup()], DEFAULT_CONTENT, trigger);
    expect(result.condition).toEqual({ field: "actor.role", operator: "eq", value: "manager" });
  });
});

// ============================================================================
// hydrateFromAPI
// ============================================================================

describe("hydrateFromAPI", () => {
  it("hydrates internal group from actions with branch_key", () => {
    const rule = makeRule({
      actions: [makeAction()],
    });

    const state = hydrateFromAPI(rule);
    expect(state.recipientGroups).toHaveLength(1);
    expect(state.recipientGroups[0].recipient_kind).toBe("internal");
    expect(state.recipientGroups[0].recipient_config?.resolver_type).toBe("lead_owner");
    expect(state.recipientGroups[0].channels).toHaveLength(1);
    expect(state.recipientGroups[0].channels[0].channel).toBe("browser");
  });

  it("hydrates external group from actions with external_resolver in config", () => {
    const rule = makeRule({
      actions: [makeAction({
        id: 2, channel: "zalo", content_mode: "channel_native",
        config: { external_resolver: "lead_contact", zalo_template_id: "ZNS_001" },
        branch_key: "ext_1_zalo", recipient_config: null,
      })],
    });

    const state = hydrateFromAPI(rule);
    expect(state.recipientGroups).toHaveLength(1);
    expect(state.recipientGroups[0].recipient_kind).toBe("external");
    expect(state.recipientGroups[0].external_resolver).toBe("lead_contact");
  });

  it("hydrates legacy rule with no actions — creates default browser group", () => {
    const rule = makeRule({ actions: [] });
    const state = hydrateFromAPI(rule);

    expect(state.recipientGroups).toHaveLength(1);
    expect(state.recipientGroups[0].group_key).toBe("default");
    expect(state.recipientGroups[0].channels).toHaveLength(1);
    expect(state.recipientGroups[0].channels[0].channel).toBe("browser");
  });

  it("detects duplicate channels in same group", () => {
    const rule = makeRule({
      actions: [
        makeAction(),
        makeAction({ id: 2, step: 2, delay_minutes: 5, branch_key: "group_1_browser2" }),
      ],
    });

    const state = hydrateFromAPI(rule);
    expect(state.recipientGroups[0]._hasDuplicateChannels).toBe(true);
  });

  it("hydrates trigger and default content", () => {
    const rule = makeRule({
      condition: { field: "actor.role", operator: "eq", value: "manager" },
    });
    const state = hydrateFromAPI(rule);

    expect(state.trigger.event).toBe("lead_created");
    expect(state.trigger.condition).toEqual({ field: "actor.role", operator: "eq", value: "manager" });
    expect(state.defaultContent.title_template).toBe("Test title");
  });
});

// ============================================================================
// validateGroups
// ============================================================================

describe("validateGroups", () => {
  it("returns error when no groups", () => {
    expect(validateGroups([])).toContain("Cần ít nhất 1 nhóm người nhận");
  });

  it("returns empty for valid internal group", () => {
    expect(validateGroups([makeInternalGroup()])).toEqual([]);
  });

  it("returns empty for valid external group with zalo template", () => {
    expect(validateGroups([makeExternalGroup()])).toEqual([]);
  });

  it("detects missing resolver on internal group", () => {
    const group = makeInternalGroup({ recipient_config: { resolver_type: "", params: {} } });
    const errors = validateGroups([group]);
    expect(errors.some((e) => e.includes("chọn người nhận"))).toBe(true);
  });

  it("detects missing external_resolver", () => {
    const group = makeExternalGroup({ external_resolver: null });
    const errors = validateGroups([group]);
    expect(errors.some((e) => e.includes("đối tượng nhận bên ngoài"))).toBe(true);
  });

  it("detects empty channels on group", () => {
    const group = makeInternalGroup({ channels: [] });
    const errors = validateGroups([group]);
    expect(errors.some((e) => e.includes("kênh gửi"))).toBe(true);
  });

  it("allows multiple browser channels across groups (PR2: multi-browser OK)", () => {
    const g1 = makeInternalGroup();
    const g2 = makeInternalGroup({
      group_key: "group_2",
      recipient_config: { resolver_type: "unit_staff", params: {} },
    });
    const errors = validateGroups([g1, g2]);
    // PR2: Multi-browser allowed — cross-action dedup in dispatcher handles precedence
    expect(errors.some((e) => e.includes("Trong"))).toBe(false);
  });

  it("detects inline_override without content", () => {
    const group = makeInternalGroup({
      channels: [{
        channel: "email",
        delay_minutes: 0,
        content_mode: "inline_override",
        template_code: null,
        content_override: { title_template: "", message_template: "" },
        config: null,
      }],
    });
    const errors = validateGroups([group]);
    expect(errors.some((e) => e.includes("soạn nội dung"))).toBe(true);
  });

  it("detects channel_native without zalo_template_id", () => {
    const group = makeExternalGroup({
      channels: [{
        channel: "zalo",
        delay_minutes: 0,
        content_mode: "channel_native",
        template_code: null,
        content_override: null,
        config: { zalo_template_id: "", zalo_template_data: {} },
      }],
    });
    const errors = validateGroups([group]);
    expect(errors.some((e) => e.includes("template Zalo"))).toBe(true);
  });

  it("flags _hasDuplicateChannels groups", () => {
    const group = makeInternalGroup({ _hasDuplicateChannels: true });
    const errors = validateGroups([group]);
    expect(errors.some((e) => e.includes("phức tạp"))).toBe(true);
  });
});

// ============================================================================
// validateStep1 / validateStep2 / validateAllSteps / flattenStepErrors
// ============================================================================

describe("per-step validation", () => {
  it("validateStep1 returns error when event is empty", () => {
    expect(validateStep1("")).toHaveLength(1);
    expect(validateStep1("lead_created")).toEqual([]);
  });

  it("validateStep2 returns errors for missing title/message", () => {
    expect(validateStep2("", "")).toHaveLength(2);
    expect(validateStep2("Title", "")).toHaveLength(1);
    expect(validateStep2("Title", "Message")).toEqual([]);
  });

  it("validateAllSteps combines all step errors", () => {
    const errors = validateAllSteps("", "", "", []);
    expect(errors.step1.length).toBeGreaterThan(0);
    expect(errors.step2.length).toBeGreaterThan(0);
    expect(errors.step3.length).toBeGreaterThan(0);
  });

  it("flattenStepErrors flattens all steps", () => {
    const errors = validateAllSteps("", "", "", []);
    const flat = flattenStepErrors(errors);
    expect(flat.length).toBe(errors.step1.length + errors.step2.length + errors.step3.length);
  });

  it("validateAllSteps returns empty for valid data", () => {
    const errors = validateAllSteps("lead_created", "Title", "Message", [makeInternalGroup()]);
    expect(flattenStepErrors(errors)).toEqual([]);
  });
});

// ============================================================================
// canSave
// ============================================================================

describe("canSave", () => {
  it("returns true for valid groups", () => {
    expect(canSave([makeInternalGroup()])).toBe(true);
  });

  it("returns false for empty groups", () => {
    expect(canSave([])).toBe(false);
  });

  it("returns false when group has duplicate channels", () => {
    expect(canSave([makeInternalGroup({ _hasDuplicateChannels: true })])).toBe(false);
  });
});

// ============================================================================
// Factory helpers
// ============================================================================

describe("factory helpers", () => {
  it("createInternalGroup returns valid group with browser channel", () => {
    resetGroupCounter();
    const group = createInternalGroup();
    expect(group.recipient_kind).toBe("internal");
    expect(group.channels[0].channel).toBe("browser");
    expect(group.group_key).toBe("group_1");
  });

  it("createExternalGroup returns valid group with zalo channel", () => {
    resetGroupCounter();
    const group = createExternalGroup();
    expect(group.recipient_kind).toBe("external");
    expect(group.channels[0].channel).toBe("zalo");
    expect(group.channels[0].content_mode).toBe("channel_native");
  });

  it("counter increments across calls", () => {
    resetGroupCounter();
    const g1 = createInternalGroup();
    const g2 = createInternalGroup();
    expect(g1.group_key).toBe("group_1");
    expect(g2.group_key).toBe("group_2");
  });
});

// ============================================================================
// Alias helpers
// ============================================================================

describe("resolveFieldAlias", () => {
  it("resolves known field aliases", () => {
    expect(resolveFieldAlias("new_status", "lead_status_changed")).toBe("event.new_status_id");
    expect(resolveFieldAlias("lead_id", "lead_created")).toBe("lead.id");
  });

  it("resolves unit_id per-event for lead_imported", () => {
    expect(resolveFieldAlias("unit_id", "lead_imported")).toBe("event.unit_id");
  });

  it("resolves unit_id default for other events", () => {
    expect(resolveFieldAlias("unit_id", "lead_created")).toBe("lead.unit_id");
  });

  it("passes through unknown fields", () => {
    expect(resolveFieldAlias("custom_field", "lead_created")).toBe("custom_field");
  });
});

describe("OPERATOR_ALIAS_MAP", () => {
  it("maps legacy operators to modern format", () => {
    expect(OPERATOR_ALIAS_MAP["=="]).toBe("eq");
    expect(OPERATOR_ALIAS_MAP["!="]).toBe("ne");
    expect(OPERATOR_ALIAS_MAP[">="]).toBe("gte");
  });
});

// =============================================================================
// Template override validation + mode switching
// =============================================================================

describe("validateGroups — template_override", () => {
  it("reports error when template_override has no template_code", () => {
    const groups: RecipientGroup[] = [
      {
        ...createInternalGroup(),
        channels: [
          {
            channel: "browser",
            delay_minutes: 0,
            content_mode: "template_override",
            template_code: null, // Missing!
            content_override: null,
            config: null,
          },
        ],
      },
    ];
    const errors = validateGroups(groups);
    expect(errors.length).toBeGreaterThan(0);
    expect(errors.some((e) => e.includes("template"))).toBe(true);
  });

  it("passes when template_override has template_code", () => {
    const groups: RecipientGroup[] = [
      {
        ...createInternalGroup(),
        channels: [
          {
            channel: "browser",
            delay_minutes: 0,
            content_mode: "template_override",
            template_code: "TPL_LEAD_ASSIGNED_V1",
            content_override: null,
            config: null,
          },
        ],
      },
    ];
    const errors = validateGroups(groups);
    // No template-related error
    expect(errors.filter((e) => e.includes("template")).length).toBe(0);
  });
});

describe("mapToAPI — template_code preservation", () => {
  it("maps template_code when content_mode is template_override", () => {
    const groups: RecipientGroup[] = [
      {
        ...createInternalGroup(),
        channels: [
          {
            channel: "browser",
            delay_minutes: 0,
            content_mode: "template_override",
            template_code: "TPL_TEST_V1",
            content_override: null,
            config: null,
          },
        ],
      },
    ];
    const defaultContent: WizardDefaultContent = {
      title_template: "Default",
      message_template: "Default msg",
      notification_type: "info",
    };
    const trigger: WizardTrigger = {
      event: "lead_assigned",
      condition: null,
      enabled: true,
    };

    const result = mapToAPI(groups, defaultContent, trigger);
    expect(result.actions![0].template_code).toBe("TPL_TEST_V1");
    expect(result.actions![0].content_mode).toBe("template_override");
  });

  it("clears template_code when switching to inherit_default", () => {
    const groups: RecipientGroup[] = [
      {
        ...createInternalGroup(),
        channels: [
          {
            channel: "browser",
            delay_minutes: 0,
            content_mode: "inherit_default",
            template_code: null, // Cleared by UI
            content_override: null,
            config: null,
          },
        ],
      },
    ];
    const defaultContent: WizardDefaultContent = {
      title_template: "Default",
      message_template: "Default msg",
      notification_type: "info",
    };
    const trigger: WizardTrigger = {
      event: "lead_assigned",
      condition: null,
      enabled: true,
    };

    const result = mapToAPI(groups, defaultContent, trigger);
    expect(result.actions![0].template_code).toBeNull();
    expect(result.actions![0].content_mode).toBe("inherit_default");
  });
});
