// wizard-utils.ts — Phase 3c data mapping between UI state and backend API
import type {
  NotificationRule,
  NotificationRuleCreate,
  NotificationActionCreate,
} from "@/types/api.types";
import type {
  RecipientGroup,
  ChannelBranch,
  WizardState,
  WizardTrigger,
  WizardDefaultContent,
} from "./wizard-types";

// ============================================================================
// UI → API: flatten recipient groups into actions array
// ============================================================================

export function mapToAPI(
  groups: RecipientGroup[],
  defaultContent: WizardDefaultContent,
  trigger: WizardTrigger,
): NotificationRuleCreate {
  let step = 0;
  const actions: NotificationActionCreate[] = [];

  for (const group of groups) {
    for (const branch of group.channels) {
      step++;
      const action: NotificationActionCreate = {
        step,
        channel: branch.channel,
        delay_minutes: branch.delay_minutes,
        content_mode: branch.content_mode,
        content_override: branch.content_override,
        branch_key: `${group.group_key}_${branch.channel}`,
        template_code: branch.template_code ?? null,
        config: branch.config,
      };

      if (group.recipient_kind === "internal") {
        action.recipient_config = group.recipient_config;
      } else {
        // External: resolver goes in config, NOT recipient_config
        action.recipient_config = null;
        action.config = {
          ...(branch.config || {}),
          external_resolver: group.external_resolver,
        };
        action.content_mode = "channel_native";
      }

      actions.push(action);
    }
  }

  // rule.recipient_config = first internal group (safe fallback for loader)
  const firstInternal = groups.find((g) => g.recipient_kind === "internal");
  const ruleRecipientConfig = firstInternal?.recipient_config ?? {
    resolver_type: "lead_owner",
    params: {},
  };

  return {
    event: trigger.event,
    condition: trigger.condition,
    title_template: defaultContent.title_template,
    message_template: defaultContent.message_template,
    notification_type: defaultContent.notification_type,
    link_template: defaultContent.link_template || undefined,
    channels: [...new Set(actions.map((a) => a.channel))],
    recipient_config: ruleRecipientConfig,
    enabled: trigger.enabled,
    actions,
  };
}

// ============================================================================
// API → UI: group actions into recipient groups
// ============================================================================

export function hydrateFromAPI(rule: NotificationRule): WizardState {
  const groupMap = new Map<string, RecipientGroup>();

  for (const action of rule.actions) {
    const isExternal =
      action.config != null &&
      typeof action.config === "object" &&
      "external_resolver" in action.config;

    const groupKey = isExternal
      ? `ext_${(action.config as Record<string, unknown>).external_resolver}`
      : JSON.stringify(action.recipient_config ?? rule.recipient_config);

    if (!groupMap.has(groupKey)) {
      if (isExternal) {
        groupMap.set(groupKey, {
          group_key:
            action.branch_key?.replace(/_[^_]+$/, "") ??
            `ext_${groupMap.size + 1}`,
          label: getExternalResolverLabel(
            String(
              (action.config as Record<string, unknown>).external_resolver,
            ),
          ),
          recipient_kind: "external",
          recipient_config: null,
          external_resolver: String(
            (action.config as Record<string, unknown>).external_resolver,
          ),
          channels: [],
        });
      } else {
        const rc = (action.recipient_config ??
          rule.recipient_config) as Record<string, unknown>;
        groupMap.set(groupKey, {
          group_key:
            action.branch_key?.replace(/_[^_]+$/, "") ??
            `group_${groupMap.size + 1}`,
          label: getResolverLabel(rc),
          recipient_kind: "internal",
          recipient_config: rc as RecipientGroup["recipient_config"],
          external_resolver: null,
          channels: [],
        });
      }
    }

    const branch: ChannelBranch = {
      channel: action.channel,
      delay_minutes: action.delay_minutes,
      content_mode:
        (action.content_mode as ChannelBranch["content_mode"]) ??
        "inherit_default",
      template_code: action.template_code ?? null,
      content_override: action.content_override as ChannelBranch["content_override"],
      config: action.config,
    };

    groupMap.get(groupKey)!.channels.push(branch);
  }

  // Legacy: no actions → 1 group from rule
  if (groupMap.size === 0) {
    const rc = rule.recipient_config as Record<string, unknown>;
    groupMap.set("default", {
      group_key: "default",
      label: getResolverLabel(rc),
      recipient_kind: "internal",
      recipient_config: rc as RecipientGroup["recipient_config"],
      external_resolver: null,
      channels:
        rule.actions.length > 0
          ? rule.actions.map((a) => ({
              channel: a.channel,
              delay_minutes: a.delay_minutes,
              content_mode: "inherit_default" as const,
              template_code: a.template_code ?? null,
              content_override: null,
              config: a.config,
            }))
          : [
              {
                channel: "browser",
                delay_minutes: 0,
                content_mode: "inherit_default" as const,
                template_code: null,
                content_override: null,
                config: null,
              },
            ],
    });
  }

  // Detect unsupported: multiple actions same channel in same group
  for (const group of groupMap.values()) {
    const channelCounts = new Map<string, number>();
    for (const ch of group.channels) {
      channelCounts.set(ch.channel, (channelCounts.get(ch.channel) || 0) + 1);
    }
    group._hasDuplicateChannels = [...channelCounts.values()].some(
      (c) => c > 1,
    );
  }

  return {
    trigger: {
      event: rule.event,
      condition: rule.condition,
      enabled: rule.enabled,
    },
    defaultContent: {
      title_template: rule.title_template,
      message_template: rule.message_template,
      notification_type: rule.notification_type,
      link_template: rule.link_template ?? "",
    },
    recipientGroups: [...groupMap.values()],
  };
}

// ============================================================================
// Label helpers
// ============================================================================

const RESOLVER_LABELS: Record<string, string> = {
  lead_owner: "Officer phụ trách lead",
  unit_staff: "Nhân viên cùng đơn vị",
  unit_managers: "Quản lý đơn vị",
  all_admins: "Tất cả Admin",
  all_users: "Tất cả người dùng",
  specific_users: "Người dùng cụ thể",
  dorm_residents: "Sinh viên ký túc",
  dorm_staff: "Nhân viên ký túc",
};

const EXTERNAL_RESOLVER_LABELS: Record<string, string> = {
  lead_contact: "Lead (qua Zalo/SMS)",
  admission_contact: "Hồ sơ tuyển sinh (qua Zalo/SMS)",
  collaborator_contact: "Cộng tác viên (qua Zalo/SMS)",
};

export function getResolverLabel(
  rc: Record<string, unknown> | null,
): string {
  if (!rc) return "Không xác định";
  const rt = String(rc.resolver_type ?? "");
  return RESOLVER_LABELS[rt] ?? rt;
}

export function getExternalResolverLabel(resolver: string): string {
  return EXTERNAL_RESOLVER_LABELS[resolver] ?? resolver;
}

// ============================================================================
// Validation helpers
// ============================================================================

export function validateGroups(groups: RecipientGroup[]): string[] {
  const errors: string[] = [];

  if (groups.length === 0) {
    errors.push("Cần ít nhất 1 nhóm người nhận");
    return errors;
  }

  // Browser count across all groups
  let browserCount = 0;
  const branchKeys = new Set<string>();

  for (const group of groups) {
    if (group._hasDuplicateChannels) {
      errors.push(
        `Nhóm "${group.label}" có cấu hình phức tạp — vui lòng chỉnh sửa qua API`,
      );
    }

    if (group.channels.length === 0) {
      errors.push(`Nhóm "${group.label}" cần chọn ít nhất 1 kênh gửi`);
    }

    if (group.recipient_kind === "internal" && !group.recipient_config?.resolver_type) {
      errors.push(`Nhóm "${group.label}" cần chọn người nhận`);
    }

    if (group.recipient_kind === "external" && !group.external_resolver) {
      errors.push(`Nhóm "${group.label}" cần chọn đối tượng nhận bên ngoài`);
    }

    for (const branch of group.channels) {
      if (branch.channel === "browser") browserCount++;

      const bk = `${group.group_key}_${branch.channel}`;
      if (branchKeys.has(bk)) {
        errors.push(`Cấu hình kênh bị trùng trong nhóm "${group.label}"`);
      }
      branchKeys.add(bk);

      if (branch.content_mode === "inline_override") {
        const co = branch.content_override;
        if (!co?.title_template && !co?.message_template) {
          errors.push(
            `Kênh ${branch.channel} trong nhóm "${group.label}" cần soạn nội dung`,
          );
        }
      }

      if (branch.content_mode === "channel_native") {
        if (
          !branch.config ||
          !(branch.config as Record<string, unknown>).zalo_template_id
        ) {
          errors.push(
            `Kênh ${branch.channel} trong nhóm "${group.label}" cần mã template Zalo`,
          );
        }
      }
    }
  }

  if (browserCount > 1) {
    errors.push("Chỉ được phép 1 kênh \"Trong ứng dụng\" cho mỗi rule");
  }

  return errors;
}

export function canSave(groups: RecipientGroup[]): boolean {
  return (
    groups.length > 0 &&
    !groups.some((g) => g._hasDuplicateChannels) &&
    validateGroups(groups).length === 0
  );
}

// ============================================================================
// Per-step validation (single source of truth for wizard nav + sidebar + preview)
// ============================================================================

export interface StepErrors {
  step1: string[];
  step2: string[];
  step3: string[];
}

export function validateStep1(event: string): string[] {
  if (!event) return ["Vui lòng chọn sự kiện"];
  return [];
}

export function validateStep2(title: string, message: string): string[] {
  const errors: string[] = [];
  if (!title) errors.push("Vui lòng nhập tiêu đề thông báo");
  if (!message) errors.push("Vui lòng nhập nội dung thông báo");
  return errors;
}

export function validateAllSteps(
  event: string,
  title: string,
  message: string,
  groups: RecipientGroup[],
): StepErrors {
  return {
    step1: validateStep1(event),
    step2: validateStep2(title, message),
    step3: validateGroups(groups),
  };
}

export function flattenStepErrors(errors: StepErrors): string[] {
  return [...errors.step1, ...errors.step2, ...errors.step3];
}

// ============================================================================
// Factory helpers
// ============================================================================

let groupCounter = 0;

export function createInternalGroup(
  resolverType: string = "lead_owner",
): RecipientGroup {
  groupCounter++;
  return {
    group_key: `group_${groupCounter}`,
    label: RESOLVER_LABELS[resolverType] ?? resolverType,
    recipient_kind: "internal",
    recipient_config: { resolver_type: resolverType, params: {} },
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
  };
}

export function createExternalGroup(
  externalResolver: string = "lead_contact",
): RecipientGroup {
  groupCounter++;
  return {
    group_key: `ext_${groupCounter}`,
    label: EXTERNAL_RESOLVER_LABELS[externalResolver] ?? externalResolver,
    recipient_kind: "external",
    recipient_config: null,
    external_resolver: externalResolver,
    channels: [
      {
        channel: "zalo",
        delay_minutes: 0,
        content_mode: "channel_native",
        template_code: null,
        content_override: null,
        config: { zalo_template_id: "", zalo_template_data: {} },
      },
    ],
  };
}

export function resetGroupCounter(): void {
  groupCounter = 0;
}

// ============================================================================
// Condition alias helpers (used by hydration to normalize legacy condition formats)
// ============================================================================

export const OPERATOR_ALIAS_MAP: Record<string, string> = {
  "==": "eq", "!=": "ne",
  ">": "gt", ">=": "gte",
  "<": "lt", "<=": "lte",
};

const FIELD_ALIAS_MAP: Record<string, string> = {
  new_status: "event.new_status_id",
  old_status: "event.old_status_id",
  old_stage: "event.old_stage_id",
  new_stage: "event.new_stage_id",
  lead_id: "lead.id",
  lead_name: "lead.name",
  officer_id: "lead.officer_id",
  actor_id: "actor.id",
  actor_name: "actor.name",
  consultation_id: "consultation.id",
  status_changed: "event.status_changed",
  updated_fields: "event.updated_fields",
};

const FIELD_ALIAS_PER_EVENT: Record<string, Record<string, string>> = {
  lead_imported: { unit_id: "event.unit_id" },
};
const FIELD_ALIAS_DEFAULT: Record<string, string> = { unit_id: "lead.unit_id" };

export function resolveFieldAlias(field: string, event: string): string {
  if (field in FIELD_ALIAS_MAP) return FIELD_ALIAS_MAP[field];
  const perEvent = FIELD_ALIAS_PER_EVENT[event] ?? FIELD_ALIAS_DEFAULT;
  return perEvent[field] ?? FIELD_ALIAS_DEFAULT[field] ?? field;
}
