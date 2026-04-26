// wizard-types.ts — Phase 3c UI types for recipient groups + channel branches

import type { ChannelInfo } from "@/types/api.types";

export type RecipientKind = "internal" | "external";

export type ContentMode = "inherit_default" | "inline_override" | "channel_native" | "template_override";

// Shared across RecipientGroupCard, ChannelBranchCard, AddChannelBar
export const CHANNEL_LABELS: Record<string, string> = {
  browser: "Trong ứng dụng",
  email: "Email",
  zalo: "Zalo",
  zalo_bot: "Zalo Bot",
  sms: "SMS",
};

// Fallback channels when metadata unavailable. Only include live channels.
// v5 pre-work: full ChannelInfo objects so callers can read internal_only.
// External fallback excludes browser implicitly via filter at the consumer.
// v5 Step 23: zalo_bot lives in the internal fallback with internal_only=true
// so RecipientGroupCard's existing `!ch.internal_only` filter (set up in
// v5-pre-2) keeps it out of external recipient pickers automatically.
export const DEFAULT_CHANNELS_INFO: Record<RecipientKind, ChannelInfo[]> = {
  internal: [
    { value: "browser", status: "live", internal_only: false },
    { value: "email", status: "live", internal_only: false },
    { value: "zalo", status: "live", internal_only: false },
    { value: "zalo_bot", status: "live", internal_only: true },
  ],
  external: [
    { value: "zalo", status: "live", internal_only: false },
  ],
};

/**
 * @deprecated v5 pre-work: use DEFAULT_CHANNELS_INFO. Retained only for tests
 * or callers that genuinely need the channel-name strings.
 */
export const DEFAULT_CHANNELS: Record<RecipientKind, string[]> = {
  internal: DEFAULT_CHANNELS_INFO.internal.map((c) => c.value),
  external: DEFAULT_CHANNELS_INFO.external.map((c) => c.value),
};

export interface ExternalResolverOption {
  value: string;
  label: string;
  description: string;
}
// "template_override" is not authorable from wizard UI (needs template picker),
// but must be preserved during hydration + save to avoid data loss.

export interface ChannelBranch {
  channel: string; // "browser" | "email" | "zalo" | "sms"
  delay_minutes: number;
  content_mode: ContentMode;
  template_code: string | null; // preserved for template_override mode
  content_override: {
    title_template?: string;
    message_template?: string;
    // PR2: link_template removed — link is code-owned
  } | null;
  config: Record<string, unknown> | null; // zalo_template_id, zalo_template_data, etc.
}

export interface RecipientGroup {
  group_key: string; // auto: "group_1", "group_2", "ext_1"
  label: string; // display from resolver option
  recipient_kind: RecipientKind;
  // Internal groups:
  recipient_config: {
    resolver_type: string;
    params: Record<string, unknown>;
  } | null;
  // External groups:
  external_resolver: string | null; // "lead_contact" | "admission_contact" | "collaborator_contact"
  channels: ChannelBranch[];
  // Flags:
  _hasDuplicateChannels?: boolean; // set during hydration, blocks save
}

export interface WizardTrigger {
  event: string;
  condition: Record<string, unknown> | null;
  enabled: boolean;
}

export interface WizardDefaultContent {
  title_template: string;
  message_template: string;
  notification_type: string;
  // PR2: link_template removed — link is code-owned (catalog)
}

export interface WizardState {
  trigger: WizardTrigger;
  defaultContent: WizardDefaultContent;
  recipientGroups: RecipientGroup[];
}
