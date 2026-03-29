// wizard-types.ts — Phase 3c UI types for recipient groups + channel branches

export type RecipientKind = "internal" | "external";

export type ContentMode = "inherit_default" | "inline_override" | "channel_native" | "template_override";
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
    link_template?: string;
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
  link_template: string;
}

export interface WizardState {
  trigger: WizardTrigger;
  defaultContent: WizardDefaultContent;
  recipientGroups: RecipientGroup[];
}
