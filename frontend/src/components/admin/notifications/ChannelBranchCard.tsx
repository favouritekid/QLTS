"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";
import type { ChannelBranch, ContentMode, RecipientKind } from "./wizard-types";
import { CHANNEL_LABELS } from "./wizard-types";

interface ChannelBranchCardProps {
  branch: ChannelBranch;
  recipientKind: RecipientKind;
  onChange: (updated: ChannelBranch) => void;
  onRemove: () => void;
}

// Extended labels for inline display (browser gets extra context)
const CHANNEL_LABELS_EXTENDED: Record<string, string> = {
  ...CHANNEL_LABELS,
  browser: "Trong ứng dụng (thời gian thực)",
};

export default function ChannelBranchCard({
  branch,
  recipientKind,
  onChange,
  onRemove,
}: ChannelBranchCardProps) {
  const isExternal = recipientKind === "external";
  const mode = branch.content_mode;
  // Raw text buffer for JSON textarea — allows typing partial/invalid JSON
  // without snapping back to last valid parse.
  const initialJson =
    typeof (branch.config as Record<string, unknown>)?.zalo_template_data === "object"
      ? JSON.stringify((branch.config as Record<string, unknown>)?.zalo_template_data, null, 2)
      : "";
  const [jsonText, setJsonText] = useState(initialJson);
  const [jsonError, setJsonError] = useState("");

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
          {CHANNEL_LABELS_EXTENDED[branch.channel] ?? branch.channel}
        </span>
        <Button variant="ghost" size="sm" onClick={onRemove} className="h-6 w-6 p-0">
          <X className="h-3 w-3" />
        </Button>
      </div>

      {/* Content mode selection — only for internal groups */}
      {!isExternal && (
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Cách hiển thị nội dung</Label>

          {/* template_override: read-only preservation (not authorable from wizard) */}
          {mode === "template_override" ? (
            <div className="rounded border border-yellow-200 bg-yellow-50 p-2 text-xs text-yellow-800">
              <p className="font-medium">Đang dùng template riêng</p>
              <p>Template: <code>{branch.template_code ?? "N/A"}</code></p>
              <p className="mt-1">Nếu muốn đổi sang nội dung khác, template hiện tại sẽ bị xóa.</p>
            </div>
          ) : (
            <div className="flex gap-3">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="radio"
                  name={`mode_${branch.channel}`}
                  checked={mode === "inherit_default"}
                  onChange={() => setMode("inherit_default")}
                />
                Dùng nội dung từ Bước 2
              </label>
              <label className="flex items-center gap-1.5 text-xs cursor-pointer">
                <input
                  type="radio"
                  name={`mode_${branch.channel}`}
                  checked={mode === "inline_override"}
                  onChange={() => setMode("inline_override")}
                />
                Soạn nội dung riêng
              </label>
            </div>
          )}

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
            <Label className="text-xs">Mã template Zalo *</Label>
            <Input
              placeholder="VD: ZNS_LEAD_CREATED"
              value={String((branch.config as Record<string, unknown>)?.zalo_template_id ?? "")}
              onChange={(e) => setConfig("zalo_template_id", e.target.value)}
              className="text-sm"
            />
          </div>
          <div>
            <Label className="text-xs">Dữ liệu template (JSON)</Label>
            <Textarea
              placeholder='{"customer": "$lead_name", "phone": "$lead_phone"}'
              value={jsonText}
              onChange={(e) => {
                const raw = e.target.value;
                setJsonText(raw);
                try {
                  setConfig("zalo_template_data", JSON.parse(raw));
                  setJsonError("");
                } catch {
                  setJsonError(raw.trim() ? "JSON không hợp lệ" : "");
                }
              }}
              className={`text-sm min-h-[60px] font-mono ${jsonError ? "border-destructive" : ""}`}
            />
            {jsonError ? (
              <p className="text-xs text-destructive mt-1">{jsonError}</p>
            ) : (
              <p className="text-xs text-muted-foreground mt-1">
                Dùng $tên_biến để chèn dữ liệu động (VD: $lead_name)
              </p>
            )}
          </div>
        </div>
      )}

      {/* Delay — for non-browser channels */}
      {branch.channel !== "browser" && (
        <div className="flex items-center gap-2">
          <Label className="text-xs text-muted-foreground whitespace-nowrap">Gửi sau:</Label>
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
