"use client";

import { Switch } from "@/components/ui/switch";
import type { RecipientGroup } from "./wizard-types";
import RuleNarrativeSummary from "./RuleNarrativeSummary";

interface ConditionSummary {
  field: string;
  operator: string;
  value: string;
}

interface FinalPreviewSectionProps {
  previewErrors: string[];
  eventLabel: string;
  titleTemplate: string;
  recipientGroups: RecipientGroup[];
  condition: ConditionSummary | null;
  enabled: boolean;
  onEnabledChange: (checked: boolean) => void;
}

export default function FinalPreviewSection({
  previewErrors,
  eventLabel,
  titleTemplate,
  recipientGroups,
  condition,
  enabled,
  onEnabledChange,
}: FinalPreviewSectionProps) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">Kiểm tra & Lưu</h3>
        <p className="text-sm text-muted-foreground">
          Xác nhận cấu hình trước khi lưu
        </p>
      </div>

      {/* Validation errors */}
      {previewErrors.length > 0 && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/5 p-4 space-y-1">
          <p className="text-sm font-medium text-destructive">
            Cần sửa trước khi lưu:
          </p>
          {previewErrors.map((err, i) => (
            <p key={i} className="text-sm text-destructive">
              {"\u2022"} {err}
            </p>
          ))}
        </div>
      )}

      {/* Narrative summary */}
      <RuleNarrativeSummary
        eventLabel={eventLabel}
        titleTemplate={titleTemplate}
        recipientGroups={recipientGroups}
        condition={condition}
      />

      {/* Enable toggle */}
      <div className="flex items-center gap-3 rounded-lg border p-3">
        <Switch checked={enabled} onCheckedChange={onEnabledChange} />
        <div>
          <p className="text-sm font-medium">Kích hoạt ngay</p>
          <p className="text-xs text-muted-foreground">
            Rule sẽ bắt đầu gửi thông báo khi sự kiện xảy ra. Tắt để tạo bản
            nháp.
          </p>
        </div>
      </div>
    </div>
  );
}
