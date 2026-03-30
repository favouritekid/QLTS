"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { RecipientGroup, WizardTrigger } from "./wizard-types";
import { CHANNEL_LABELS } from "./wizard-types";

interface NotificationRuleSidebarProps {
  trigger: WizardTrigger;
  recipientGroups: RecipientGroup[];
  titleTemplate: string;
  validationErrors: string[];
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
  isEditMode: boolean;
  canSave: boolean;
  selectedEventLabel?: string;
}

export default function NotificationRuleSidebar({
  trigger,
  recipientGroups,
  titleTemplate,
  validationErrors,
  enabled,
  onEnabledChange,
  onSave,
  onCancel,
  isSaving,
  isEditMode,
  canSave,
  selectedEventLabel,
}: NotificationRuleSidebarProps) {
  // Collect all channels used
  const channelsUsed = new Set<string>();
  for (const group of recipientGroups) {
    for (const ch of group.channels) {
      channelsUsed.add(ch.channel);
    }
  }

  const hasErrors = validationErrors.length > 0;
  const hasBlockingIssues = recipientGroups.some((g) => g._hasDuplicateChannels);

  return (
    <div className="space-y-4">
      {/* Status */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">
                {enabled ? "Đang bật" : "Bản nháp"}
              </p>
              <p className="text-xs text-muted-foreground">
                {enabled
                  ? "Rule sẽ gửi thông báo khi sự kiện xảy ra"
                  : "Rule chưa hoạt động"}
              </p>
            </div>
            <Switch checked={enabled} onCheckedChange={onEnabledChange} />
          </div>
        </CardContent>
      </Card>

      {/* Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Tóm tắt</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div>
            <span className="text-muted-foreground">Sự kiện: </span>
            <span className="font-medium">
              {selectedEventLabel || trigger.event || "Chưa chọn"}
            </span>
          </div>

          {trigger.condition && (
            <div>
              <span className="text-muted-foreground">Điều kiện: </span>
              <span className="text-xs">Có</span>
            </div>
          )}

          <div>
            <span className="text-muted-foreground">Nhóm nhận: </span>
            <span>{recipientGroups.length}</span>
          </div>

          {channelsUsed.size > 0 && (
            <div>
              <span className="text-muted-foreground">Kênh: </span>
              <span>
                {[...channelsUsed]
                  .map((ch) => CHANNEL_LABELS[ch] ?? ch)
                  .join(", ")}
              </span>
            </div>
          )}

          {titleTemplate && (
            <div>
              <span className="text-muted-foreground">Tiêu đề: </span>
              <span className="text-xs truncate block">{titleTemplate}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Validation */}
      {hasErrors && (
        <Card className="border-destructive/50">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-destructive flex items-center gap-1.5">
              <AlertCircle className="h-4 w-4" />
              Cần sửa ({validationErrors.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {validationErrors.map((err, i) => (
              <p key={i} className="text-xs text-destructive">
                • {err}
              </p>
            ))}
          </CardContent>
        </Card>
      )}

      {!hasErrors && recipientGroups.length > 0 && (
        <Card className="border-green-200">
          <CardContent className="pt-4">
            <p className="text-sm text-green-700 flex items-center gap-1.5">
              <CheckCircle2 className="h-4 w-4" />
              Sẵn sàng lưu
            </p>
          </CardContent>
        </Card>
      )}

      {/* Action bar */}
      <div className="space-y-2">
        <Button
          className="w-full"
          onClick={onSave}
          disabled={!canSave || isSaving || hasBlockingIssues}
        >
          {isSaving ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Đang lưu...
            </>
          ) : isEditMode ? (
            "Cập nhật quy tắc"
          ) : (
            "Lưu quy tắc"
          )}
        </Button>
        <Button variant="outline" className="w-full" onClick={onCancel}>
          Hủy
        </Button>
      </div>
    </div>
  );
}
