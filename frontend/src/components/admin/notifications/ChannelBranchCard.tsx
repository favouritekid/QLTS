"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";
import type { ChannelBranch, ContentMode, RecipientKind } from "./wizard-types";

interface ChannelBranchCardProps {
  branch: ChannelBranch;
  recipientKind: RecipientKind;
  onChange: (updated: ChannelBranch) => void;
  onRemove: () => void;
}

const CHANNEL_LABELS: Record<string, string> = {
  browser: "Browser (th\u1eddi gian th\u1ef1c)",
  email: "Email",
  zalo: "Zalo",
  sms: "SMS",
};

export default function ChannelBranchCard({
  branch,
  recipientKind,
  onChange,
  onRemove,
}: ChannelBranchCardProps) {
  const isExternal = recipientKind === "external";
  const mode = branch.content_mode;

  const setMode = (m: ContentMode) => {
    onChange({ ...branch, content_mode: m, content_override: m === "inline_override" ? { title_template: "", message_template: "" } : null });
  };

  const setOverride = (field: string, value: string) => {
    onChange({
      ...branch,
      content_override: { ...(branch.content_override || {}), [field]: value },
    });
  };

  const setConfig = (key: string, value: unknown) => {
    onChange({
      ...branch,
      config: { ...(branch.config || {}), [key]: value },
    });
  };

  return (
    <div className="rounded-lg border p-3 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">
          {CHANNEL_LABELS[branch.channel] ?? branch.channel}
        </span>
        <Button variant="ghost" size="sm" onClick={onRemove} className="h-6 w-6 p-0">
          <X className="h-3 w-3" />
        </Button>
      </div>

      {/* Content mode selection — only for internal groups */}
      {!isExternal && (
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">N\u1ed9i dung</Label>
          <div className="flex gap-3">
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="radio"
                name={`mode_${branch.channel}`}
                checked={mode === "inherit_default"}
                onChange={() => setMode("inherit_default")}
              />
              M\u1eb7c \u0111\u1ecbnh
            </label>
            <label className="flex items-center gap-1.5 text-xs cursor-pointer">
              <input
                type="radio"
                name={`mode_${branch.channel}`}
                checked={mode === "inline_override"}
                onChange={() => setMode("inline_override")}
              />
              N\u1ed9i dung ri\u00eang
            </label>
          </div>

          {/* Inline override fields */}
          {mode === "inline_override" && (
            <div className="space-y-2 pl-4 border-l-2 border-primary/20">
              <Input
                placeholder="Ti\u00eau \u0111\u1ec1 ri\u00eang (VD: Lead m\u1edbi c\u1ea7n x\u1eed l\u00fd)"
                value={branch.content_override?.title_template ?? ""}
                onChange={(e) => setOverride("title_template", e.target.value)}
                className="text-sm"
              />
              <Textarea
                placeholder="N\u1ed9i dung ri\u00eang"
                value={branch.content_override?.message_template ?? ""}
                onChange={(e) => setOverride("message_template", e.target.value)}
                className="text-sm min-h-[60px]"
              />
            </div>
          )}
        </div>
      )}

      {/* Channel native config — for external groups (zalo/sms) */}
      {isExternal && (branch.channel === "zalo" || branch.channel === "sms") && (
        <div className="space-y-2">
          <div>
            <Label className="text-xs">Zalo Template ID *</Label>
            <Input
              placeholder="VD: ZNS_LEAD_CREATED"
              value={String((branch.config as Record<string, unknown>)?.zalo_template_id ?? "")}
              onChange={(e) => setConfig("zalo_template_id", e.target.value)}
              className="text-sm"
            />
          </div>
          <div>
            <Label className="text-xs">Template Data (JSON)</Label>
            <Textarea
              placeholder='{"customer": "$lead_name", "phone": "$lead_phone"}'
              value={
                typeof (branch.config as Record<string, unknown>)?.zalo_template_data === "object"
                  ? JSON.stringify((branch.config as Record<string, unknown>)?.zalo_template_data, null, 2)
                  : ""
              }
              onChange={(e) => {
                try {
                  setConfig("zalo_template_data", JSON.parse(e.target.value));
                } catch {
                  // Keep as-is while typing
                }
              }}
              className="text-sm min-h-[60px] font-mono"
            />
          </div>
        </div>
      )}

      {/* Delay — for non-browser channels */}
      {branch.channel !== "browser" && (
        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground whitespace-nowrap">Delay:</Label>
          <Input
            type="number"
            min={0}
            value={branch.delay_minutes}
            onChange={(e) => onChange({ ...branch, delay_minutes: parseInt(e.target.value) || 0 })}
            className="w-20 text-sm"
          />
          <span className="text-xs text-muted-foreground">ph\u00fat</span>
        </div>
      )}
    </div>
  );
}
