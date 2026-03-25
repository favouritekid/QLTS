// src/components/admin/notifications/MultiStepActionEditor.tsx
/**
 * ✅ NOTIFICATION 2.0 - Multi-Step Action Editor
 *
 * Component for creating and managing multi-step notification workflows.
 * Allows configuring sequential actions with different channels and delays.
 *
 * Features:
 * - Add/remove/reorder action steps
 * - Per-step channel selection
 * - Delay configuration (minutes)
 * - Template selection per step
 * - Drag & drop reordering
 * - Visual timeline preview
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
    description: "Hiển thị popup trong trình duyệt ngay lập tức",
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
    label: "Zalo (Planned)",
    icon: MessageSquare,
    color: "bg-muted text-muted-foreground",
    description: "Gửi tin nhắn qua Zalo OA — chưa khả dụng",
    status: "planned" as const,
  },
  sms: {
    label: "SMS (Planned)",
    icon: Smartphone,
    color: "bg-muted text-muted-foreground",
    description: "Gửi tin nhắn SMS — chưa khả dụng",
    status: "planned" as const,
  },
} as const;

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
            {/* Reorder Buttons */}
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

            {/* Expand/Collapse */}
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setExpanded(!expanded)}
              aria-label={expanded ? "Thu gọn" : "Mở rộng"}
            >
              <GripVertical className="h-4 w-4" />
            </Button>

            {/* Remove */}
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
              onValueChange={(value) => onUpdate({ channel: value })}
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

          {/* Delay Configuration */}
          <div className="space-y-2">
            <Label>Độ trễ (phút)</Label>
            <Input
              type="number"
              min="0"
              step="1"
              value={action.delay_minutes || 0}
              onChange={(e) => onUpdate({ delay_minutes: parseInt(e.target.value) || 0 })}
              placeholder="0"
            />
            <p className="text-xs text-muted-foreground">
              {action.delay_minutes === 0
                ? "Gửi ngay lập tức"
                : `Gửi sau ${formatDelay(action.delay_minutes || 0)}`}
            </p>
          </div>

          {/* Template Code (Optional) */}
          <div className="space-y-2">
            <Label>
              Template Code <span className="text-muted-foreground">(Tùy chọn)</span>
            </Label>
            <Input
              value={action.template_code || ""}
              onChange={(e) => onUpdate({ template_code: e.target.value || null })}
              placeholder="VD: TPL_LEAD_ASSIGNED_EMAIL"
            />
            <p className="text-xs text-muted-foreground">
              Để trống để sử dụng template mặc định của rule
            </p>
          </div>
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
    // Renumber steps
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
    // Renumber steps
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
    // Renumber steps
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
            {actions.length} bước • Tổng thời gian: {formatDelay(totalDuration)}
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
            <CardTitle className="text-sm">📅 Timeline Preview</CardTitle>
            <CardDescription className="text-xs">
              Quy trình gửi thông báo theo thời gian
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {actions.map((action, index) => {
                const delay = getTotalDelay(actions, index + 1);
                const channelConfig = CHANNEL_CONFIG[action.channel as keyof typeof CHANNEL_CONFIG];
                const Icon = channelConfig?.icon || Bell;
                return (
                  <div key={index} className="flex items-center gap-3 text-xs">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
                      {action.step}
                    </div>
                    <Badge variant="outline" className="w-24">
                      {formatDelay(delay)}
                    </Badge>
                    <div className="flex items-center gap-1">
                      <Icon className="h-3 w-3" />
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
        <p className="font-medium mb-1">💡 Mẹo sử dụng:</p>
        <ul className="list-disc list-inside space-y-0.5 text-xs">
          <li>Bước 1 thường gửi qua Browser để thông báo ngay</li>
          <li>Bước 2+ có thể gửi qua Email/SMS với độ trễ để nhắc nhở</li>
          <li>Sử dụng độ trễ để tránh spam notifications</li>
          <li>Kéo thả để sắp xếp lại thứ tự các bước</li>
        </ul>
      </div>
    </div>
  );
}
