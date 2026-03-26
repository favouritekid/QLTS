// src/components/admin/notifications/MultiStepActionEditor.tsx
/**
 * ✅ NOTIFICATION 2.0 + Phase C1 - Multi-Step Action Editor
 *
 * Component for creating and managing multi-step notification workflows.
 * Phase C1 changes:
 * - Delay unlocked (was locked to 0 in C0)
 * - template_code disabled (deferred to D8)
 * - Zalo config fields: zalo_template_id, zalo_template_data, external_resolver
 */
"use client";

import { useState } from "react";
import {
  GripVertical,
  Plus,
  Trash2,
  Clock,
  Mail,
  Bell,
  MessageSquare,
  Smartphone,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import type { NotificationActionCreate } from "@/types/api.types";

// ============================================
// TYPES
// ============================================

interface MultiStepActionEditorProps {
  actions: NotificationActionCreate[];
  onChange: (actions: NotificationActionCreate[]) => void;
  availableChannels: string[];
}

// ============================================
// CHANNEL CONFIGURATION
// ============================================

const CHANNEL_CONFIG = {
  browser: {
    label: "Browser (Real-time)",
    icon: Bell,
    color: "bg-info-100 text-info-800 dark:bg-info-900 dark:text-info-200",
    description: "Push notification trong trình duyệt",
    status: "live" as const,
  },
  email: {
    label: "Email",
    icon: Mail,
    color: "bg-success-100 text-success-800 dark:bg-success-900 dark:text-success-200",
    description: "Gửi email đến hộp thư của người dùng",
    status: "live" as const,
  },
  zalo: {
    label: "Zalo ZNS",
    icon: MessageSquare,
    color: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    description: "Gửi tin ZNS qua Zalo OA",
    status: "live" as const,
  },
  sms: {
    label: "SMS (Planned)",
    icon: Smartphone,
    color: "bg-muted text-muted-foreground",
    description: "Gửi tin nhắn SMS — chưa khả dụng",
    status: "planned" as const,
  },
} as const;

const NONE_SENTINEL = "__none__";

const EXTERNAL_RESOLVER_OPTIONS = [
  { value: NONE_SENTINEL, label: "Không dùng" },
  { value: "lead_contact", label: "Lead Contact (SĐT/Email từ Lead)" },
  { value: "admission_contact", label: "Admission Contact (từ Hồ sơ)" },
  { value: "collaborator_contact", label: "CTV Contact (từ CTV)" },
] as const;

// ============================================
// HELPER FUNCTIONS
// ============================================

function formatDelay(minutes: number): string {
  if (minutes === 0) return "Ngay lập tức";
  if (minutes < 60) return `Sau ${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (remainingMinutes === 0) return `Sau ${hours} giờ`;
  return `Sau ${hours} giờ ${remainingMinutes} phút`;
}

function getTotalDelay(actions: NotificationActionCreate[], upToStep: number): number {
  return actions.slice(0, upToStep).reduce((sum, action) => sum + (action.delay_minutes || 0), 0);
}

function getActionConfig(action: NotificationActionCreate): Record<string, unknown> {
  return (action.config as Record<string, unknown>) || {};
}

function updateActionConfig(
  action: NotificationActionCreate,
  key: string,
  value: unknown
): Record<string, unknown> | null {
  const config = { ...getActionConfig(action), [key]: value };
  // Remove empty/null values
  if (value === "" || value === null || value === undefined) {
    delete config[key];
  }
  return Object.keys(config).length > 0 ? config : null;
}

// ============================================
// ACTION STEP COMPONENT
// ============================================

interface ActionStepProps {
  action: NotificationActionCreate;
  index: number;
  totalSteps: number;
  availableChannels: string[];
  cumulativeDelay: number;
  onUpdate: (updates: Partial<NotificationActionCreate>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

function ActionStep({
  action,
  index,
  totalSteps,
  availableChannels,
  cumulativeDelay,
  onUpdate,
  onRemove,
  onMoveUp,
  onMoveDown,
}: ActionStepProps) {
  const [expanded, setExpanded] = useState(true);
  const channelConfig = CHANNEL_CONFIG[action.channel as keyof typeof CHANNEL_CONFIG];
  const Icon = channelConfig?.icon || Bell;
  const isZalo = action.channel === "zalo";
  const actionConfig = getActionConfig(action);

  return (
    <Card className="relative">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Step Number */}
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground text-sm font-bold">
              {action.step}
            </div>

            {/* Channel Badge */}
            {channelConfig && (
              <Badge className={channelConfig.color} variant="secondary">
                <Icon className="mr-1 h-3 w-3" />
                {channelConfig.label}
              </Badge>
            )}

            {/* Delay Badge */}
            <Badge variant="outline" className="gap-1">
              <Clock className="h-3 w-3" />
              {formatDelay(cumulativeDelay)}
            </Badge>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-1">
            <div className="flex flex-col gap-0">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={onMoveUp}
                disabled={index === 0}
                aria-label="Di chuyển lên"
              >
                <ChevronUp className="h-3 w-3" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={onMoveDown}
                disabled={index === totalSteps - 1}
                aria-label="Di chuyển xuống"
              >
                <ChevronDown className="h-3 w-3" />
              </Button>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setExpanded(!expanded)}
              aria-label={expanded ? "Thu gọn" : "Mở rộng"}
            >
              <GripVertical className="h-4 w-4" />
            </Button>
            {totalSteps > 1 && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={onRemove}
                className="text-destructive hover:text-destructive"
                aria-label="Xóa bước"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4">
          {/* Channel Selection */}
          <div className="space-y-2">
            <Label>Kênh gửi</Label>
            <Select
              value={action.channel}
              onValueChange={(value) => {
                const updates: Partial<NotificationActionCreate> = { channel: value };
                // Clear zalo config if switching away from zalo
                if (value !== "zalo" && isZalo) {
                  updates.config = null;
                }
                onUpdate(updates);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {availableChannels.map((channel) => {
                  const config = CHANNEL_CONFIG[channel as keyof typeof CHANNEL_CONFIG];
                  if (!config) return null;
                  const ChannelIcon = config.icon;
                  return (
                    <SelectItem key={channel} value={channel}>
                      <div className="flex items-center gap-2">
                        <ChannelIcon className="h-4 w-4" />
                        <span>{config.label}</span>
                      </div>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
            {channelConfig && (
              <p className="text-xs text-muted-foreground">{channelConfig.description}</p>
            )}
          </div>

          {/* Delay Configuration — Phase C1: unlocked */}
          <div className="space-y-2">
            <Label>Độ trễ (phút)</Label>
            <Input
              type="number"
              min="0"
              max="10080"
              step="1"
              value={action.delay_minutes || 0}
              onChange={(e) => onUpdate({ delay_minutes: Math.max(0, parseInt(e.target.value) || 0) })}
              placeholder="0"
            />
            <p className="text-xs text-muted-foreground">
              0 = gửi ngay. Browser luôn gửi ngay. Email/Zalo qua worker.
            </p>
          </div>

          {/* Template Code — Phase D8: disabled */}
          <div className="space-y-2">
            <Label className="text-muted-foreground">
              Template Code <Badge variant="outline" className="ml-1 text-[10px]">D8</Badge>
            </Label>
            <Input
              value=""
              disabled
              placeholder="Chưa hỗ trợ — sử dụng template rule-level"
              className="bg-muted"
            />
            <p className="text-xs text-muted-foreground">
              Per-action template sẽ hỗ trợ ở Phase D8.
            </p>
          </div>

          {/* Zalo-specific Config Fields */}
          {isZalo && (
            <>
              <Separator />
              <div className="space-y-4">
                <h5 className="text-sm font-medium flex items-center gap-2">
                  <MessageSquare className="h-4 w-4" />
                  Cấu hình Zalo ZNS
                </h5>

                {/* Zalo Template ID */}
                <div className="space-y-2">
                  <Label>
                    Template ID <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    value={(actionConfig.zalo_template_id as string) || ""}
                    onChange={(e) =>
                      onUpdate({ config: updateActionConfig(action, "zalo_template_id", e.target.value) })
                    }
                    placeholder="VD: 7895417a7d3f9461cd2e"
                  />
                  <p className="text-xs text-muted-foreground">
                    ID template ZNS đã được duyệt trên Zalo Business
                  </p>
                </div>

                {/* Zalo Template Data */}
                <div className="space-y-2">
                  <Label>Template Data (JSON)</Label>
                  <Textarea
                    value={
                      actionConfig.zalo_template_data
                        ? JSON.stringify(actionConfig.zalo_template_data, null, 2)
                        : ""
                    }
                    onChange={(e) => {
                      try {
                        const parsed = e.target.value ? JSON.parse(e.target.value) : null;
                        onUpdate({ config: updateActionConfig(action, "zalo_template_data", parsed) });
                      } catch {
                        // Don't update on invalid JSON — user is still typing
                      }
                    }}
                    placeholder={`{\n  "customer": "$lead_name",\n  "phone": "$lead_phone"\n}`}
                    rows={4}
                    className="font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">
                    Dùng $field_name cho placeholder (VD: $lead_name, $officer_name)
                  </p>
                </div>

                {/* External Resolver */}
                <div className="space-y-2">
                  <Label>External Recipient</Label>
                  <Select
                    value={(actionConfig.external_resolver as string) || NONE_SENTINEL}
                    onValueChange={(value) =>
                      onUpdate({ config: updateActionConfig(action, "external_resolver", value === NONE_SENTINEL ? null : value) })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn nguồn recipient ngoài hệ thống" />
                    </SelectTrigger>
                    <SelectContent>
                      {EXTERNAL_RESOLVER_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground">
                    Gửi Zalo đến SĐT của lead/hồ sơ/CTV (ngoài hệ thống user)
                  </p>
                </div>
              </div>
            </>
          )}

          {/* Email external resolver (optional) */}
          {action.channel === "email" && (
            <div className="space-y-2">
              <Label>External Recipient (tùy chọn)</Label>
              <Select
                value={(actionConfig.external_resolver as string) || NONE_SENTINEL}
                onValueChange={(value) =>
                  onUpdate({ config: updateActionConfig(action, "external_resolver", value === NONE_SENTINEL ? null : value) })
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="Không dùng" />
                </SelectTrigger>
                <SelectContent>
                  {EXTERNAL_RESOLVER_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Gửi email đến địa chỉ của lead/hồ sơ/CTV ngoài hệ thống
              </p>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

// ============================================
// MAIN COMPONENT
// ============================================

export function MultiStepActionEditor({
  actions,
  onChange,
  availableChannels,
}: MultiStepActionEditorProps) {
  const handleAddStep = () => {
    const newStep = actions.length + 1;
    const newAction: NotificationActionCreate = {
      step: newStep,
      channel: availableChannels[0] || "browser",
      delay_minutes: 0,
      template_code: null,
      config: null,
    };
    onChange([...actions, newAction]);
  };

  const handleRemoveStep = (index: number) => {
    const newActions = actions.filter((_, i) => i !== index);
    const renumbered = newActions.map((action, i) => ({
      ...action,
      step: i + 1,
    }));
    onChange(renumbered);
  };

  const handleUpdateStep = (index: number, updates: Partial<NotificationActionCreate>) => {
    const newActions = actions.map((action, i) =>
      i === index ? { ...action, ...updates } : action
    );
    onChange(newActions);
  };

  const handleMoveUp = (index: number) => {
    if (index === 0) return;
    const newActions = [...actions];
    [newActions[index - 1], newActions[index]] = [newActions[index], newActions[index - 1]];
    const renumbered = newActions.map((action, i) => ({
      ...action,
      step: i + 1,
    }));
    onChange(renumbered);
  };

  const handleMoveDown = (index: number) => {
    if (index === actions.length - 1) return;
    const newActions = [...actions];
    [newActions[index], newActions[index + 1]] = [newActions[index + 1], newActions[index]];
    const renumbered = newActions.map((action, i) => ({
      ...action,
      step: i + 1,
    }));
    onChange(renumbered);
  };

  const totalDuration = actions.reduce((sum, action) => sum + (action.delay_minutes || 0), 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-semibold">Quy trình gửi thông báo</h4>
          <p className="text-xs text-muted-foreground">
            {actions.length} bước {totalDuration > 0 && `• Tổng thời gian: ${formatDelay(totalDuration)}`}
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={handleAddStep}>
          <Plus className="mr-2 h-4 w-4" />
          Thêm bước
        </Button>
      </div>

      <Separator />

      {/* Action Steps */}
      <div className="space-y-3">
        {actions.map((action, index) => {
          const cumulativeDelay = getTotalDelay(actions, index + 1);
          return (
            <ActionStep
              key={index}
              action={action}
              index={index}
              totalSteps={actions.length}
              availableChannels={availableChannels}
              cumulativeDelay={cumulativeDelay}
              onUpdate={(updates) => handleUpdateStep(index, updates)}
              onRemove={() => handleRemoveStep(index)}
              onMoveUp={() => handleMoveUp(index)}
              onMoveDown={() => handleMoveDown(index)}
            />
          );
        })}
      </div>

      {/* Empty State */}
      {actions.length === 0 && (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center gap-2 py-8">
            <Bell className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Chưa có bước nào</p>
            <Button type="button" variant="outline" size="sm" onClick={handleAddStep}>
              <Plus className="mr-2 h-4 w-4" />
              Thêm bước đầu tiên
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Timeline Preview */}
      {actions.length > 1 && (
        <Card className="bg-muted/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Timeline Preview</CardTitle>
            <CardDescription className="text-xs">
              Quy trình gửi thông báo theo thời gian
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {actions.map((action, index) => {
                const delay = getTotalDelay(actions, index + 1);
                const channelConfig = CHANNEL_CONFIG[action.channel as keyof typeof CHANNEL_CONFIG];
                const StepIcon = channelConfig?.icon || Bell;
                return (
                  <div key={index} className="flex items-center gap-3 text-xs">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
                      {action.step}
                    </div>
                    <Badge variant="outline" className="w-24">
                      {formatDelay(delay)}
                    </Badge>
                    <div className="flex items-center gap-1">
                      <StepIcon className="h-3 w-3" />
                      <span>{channelConfig?.label}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Help Text */}
      <div className="rounded-lg bg-info-50 border border-info-200 p-3 text-xs text-info-900 dark:bg-info-950 dark:text-info-100">
        <p className="font-medium mb-1">Mẹo:</p>
        <ul className="list-disc list-inside space-y-0.5 text-xs">
          <li>Browser gửi ngay (real-time). Email/Zalo qua worker (hỗ trợ delay).</li>
          <li>Zalo yêu cầu Template ID đã duyệt trên Zalo Business.</li>
          <li>Dùng $field_name trong Template Data để chèn dữ liệu runtime.</li>
          <li>External Recipient gửi đến SĐT/email ngoài hệ thống user.</li>
        </ul>
      </div>
    </div>
  );
}
