"use client";

import type { RecipientGroup } from "./wizard-types";
import { CHANNEL_LABELS } from "./wizard-types";

interface ConditionSummary {
  field: string;
  operator: string;
  value: string;
}

interface RuleNarrativeSummaryProps {
  eventLabel: string;
  titleTemplate: string;
  recipientGroups: RecipientGroup[];
  condition: ConditionSummary | null;
}

const CONTENT_MODE_LABELS: Record<string, string> = {
  inherit_default: "nội dung mặc định",
  inline_override: "nội dung riêng",
  template_override: "template riêng",
  channel_native: "template kênh",
};

export default function RuleNarrativeSummary({
  eventLabel,
  titleTemplate,
  recipientGroups,
  condition,
}: RuleNarrativeSummaryProps) {
  return (
    <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
      <p className="text-sm font-medium">Tóm tắt quy tắc:</p>

      <p className="text-sm">
        <span className="font-medium">Khi:</span> {eventLabel}
        {condition && (
          <span className="text-muted-foreground">
            {" "}(với điều kiện {condition.field} {condition.operator}{" "}
            &quot;{condition.value}&quot;)
          </span>
        )}
      </p>

      <p className="text-sm">
        <span className="font-medium">Nội dung:</span>{" "}
        {titleTemplate || "(chưa soạn)"}
      </p>

      <div className="text-sm space-y-2">
        <p className="font-medium">Gửi cho:</p>
        {recipientGroups.map((group) => (
          <div
            key={group.group_key}
            className="pl-4 border-l-2 border-primary/30 space-y-0.5"
          >
            <p className="font-medium">{group.label}</p>
            {group.channels.map((ch, j) => (
              <p key={j} className="text-muted-foreground">
                {"\u2192"} Qua {CHANNEL_LABELS[ch.channel] ?? ch.channel} (
                {CONTENT_MODE_LABELS[ch.content_mode] ?? ch.content_mode})
                {ch.delay_minutes > 0 && `, sau ${ch.delay_minutes} phút`}
              </p>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
