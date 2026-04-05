"use client";

import { useEffect, useRef, useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Eye, AlertCircle } from "lucide-react";
import type { RecipientGroup } from "./wizard-types";
import RuleNarrativeSummary from "./RuleNarrativeSummary";
import {
  usePreviewNotificationRule,
  type PreviewRequest,
  type ActionPreview,
} from "@/hooks/useNotificationRules";

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
  // PR2: Preview API data
  event: string;
  messageTemplate: string;
  actions: Array<{
    step: number;
    channel: string;
    branch_key?: string | null;
    content_mode?: string | null;
    content_override?: Record<string, string> | null;
    delay_minutes?: number;
    template_code?: string | null;
  }>;
  samplePayload: Record<string, string>;
}

const CHANNEL_LABELS: Record<string, string> = {
  browser: "Trong ứng dụng",
  email: "Email",
  zalo: "Zalo",
  sms: "SMS",
};

// Sample values for common variable types
const SAMPLE_VALUES: Record<string, string> = {
  lead_id: "123",
  lead_name: "Nguyễn Văn A",
  lead_phone: "0909123456",
  officer_id: "45",
  actor_id: "1",
  actor_name: "Trần Thị B",
  unit_id: "3",
  application_id: "789",
  consultation_id: "456",
  claim_id: "101",
  collaborator_id: "55",
  collaborator_name: "Lê Văn C",
  amount: "5000000",
  payment_id: "321",
  old_status: "draft",
  new_status: "submitted",
  message: "Thông báo hệ thống",
  title: "Thông báo",
  severity: "warning",
  username: "user01",
  user_id: "10",
};

function buildSamplePayload(variables: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, _] of Object.entries(variables)) {
    result[key] = SAMPLE_VALUES[key] ?? key;
  }
  return result;
}

function ActionPreviewCard({ action }: { action: ActionPreview }) {
  return (
    <div className="rounded-lg border p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-xs">
          Step {action.step}
        </Badge>
        <Badge variant="secondary" className="text-xs">
          {CHANNEL_LABELS[action.channel] ?? action.channel}
        </Badge>
        {action.branch_key && (
          <Badge variant="outline" className="text-xs">
            {action.branch_key}
          </Badge>
        )}
        {action.delay_minutes > 0 && (
          <span className="text-xs text-muted-foreground">
            +{action.delay_minutes} phút
          </span>
        )}
      </div>
      <div className="bg-muted/50 rounded p-3 space-y-1.5">
        <p className="font-semibold text-sm">{action.rendered_title}</p>
        <p className="text-sm text-muted-foreground">
          {action.rendered_message}
        </p>
        {action.rendered_link && (
          <p className="text-xs text-blue-600">{action.rendered_link}</p>
        )}
      </div>
    </div>
  );
}

export default function FinalPreviewSection({
  previewErrors,
  eventLabel,
  titleTemplate,
  recipientGroups,
  condition,
  enabled,
  onEnabledChange,
  event,
  messageTemplate,
  actions,
  samplePayload,
}: FinalPreviewSectionProps) {
  const previewMutation = usePreviewNotificationRule();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedReady, setDebouncedReady] = useState(false);

  // Debounced preview fetch (400ms)
  useEffect(() => {
    if (!event || !titleTemplate) {
      setDebouncedReady(false);
      return;
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(() => {
      const enrichedPayload = buildSamplePayload(samplePayload);

      const request: PreviewRequest = {
        event,
        title_template: titleTemplate,
        message_template: messageTemplate,
        sample_payload: enrichedPayload,
        actions:
          actions.length > 0
            ? actions
            : [{ step: 1, channel: "browser", delay_minutes: 0 }],
      };

      previewMutation.mutate(request);
      setDebouncedReady(true);
    }, 400);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event, titleTemplate, messageTemplate, JSON.stringify(samplePayload), JSON.stringify(actions)]);

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
              {"•"} {err}
            </p>
          ))}
        </div>
      )}

      {/* PR2: Live preview from API */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <Eye className="h-4 w-4" />
            Xem trước nội dung thông báo
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {previewMutation.isPending && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Đang tải xem trước...
            </div>
          )}

          {previewMutation.isError && (
            <div className="flex items-center gap-2 text-sm text-destructive">
              <AlertCircle className="h-4 w-4" />
              Không thể tải xem trước. Kiểm tra lại cấu hình sự kiện.
            </div>
          )}

          {previewMutation.data && (
            <>
              {previewMutation.data.rendered_link && (
                <div className="text-xs text-muted-foreground">
                  Liên kết:{" "}
                  <span className="text-blue-600">
                    {previewMutation.data.rendered_link}
                  </span>
                  {previewMutation.data.link_strategy && (
                    <span className="ml-2 text-muted-foreground/60">
                      (strategy: {previewMutation.data.link_strategy})
                    </span>
                  )}
                </div>
              )}
              {previewMutation.data.actions.map((action) => (
                <ActionPreviewCard
                  key={`${action.step}-${action.branch_key ?? action.channel}`}
                  action={action}
                />
              ))}
            </>
          )}

          {!previewMutation.isPending &&
            !previewMutation.isError &&
            !previewMutation.data &&
            !debouncedReady && (
              <p className="text-sm text-muted-foreground">
                Chọn sự kiện và nhập nội dung để xem trước.
              </p>
            )}
        </CardContent>
      </Card>

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
