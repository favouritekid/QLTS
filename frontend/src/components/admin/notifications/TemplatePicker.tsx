"use client";

import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { useNotificationTemplates } from "@/hooks/useNotificationTemplates";
import { Loader2 } from "lucide-react";

interface TemplatePickerProps {
  event: string;
  channel: string;
  value: string | null;
  onChange: (templateCode: string | null) => void;
}

export default function TemplatePicker({
  event,
  channel,
  value,
  onChange,
}: TemplatePickerProps) {
  const { data, isLoading, isError } = useNotificationTemplates({
    allowed_event: event || undefined,
    supported_channel: channel || undefined,
    page: 1,
    page_size: 50,
  });

  const templates = data?.templates ?? [];

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
        <Loader2 className="h-3 w-3 animate-spin" />
        {"Đang tải thư viện template..."}
      </div>
    );
  }

  if (isError) {
    return (
      <p className="text-xs text-destructive py-1">
        {"Không thể tải danh sách template."}
      </p>
    );
  }

  if (templates.length === 0) {
    return (
      <p className="text-xs text-muted-foreground py-1">
        {"Chưa có template phù hợp cho sự kiện/kênh này."}
      </p>
    );
  }

  return (
    <Select
      value={value ?? ""}
      onValueChange={(v) => onChange(v || null)}
    >
      <SelectTrigger className="text-sm">
        <SelectValue placeholder="Chọn template..." />
      </SelectTrigger>
      <SelectContent>
        {templates.map((tpl) => (
          <SelectItem key={tpl.template_code} value={tpl.template_code}>
            <span className="text-sm">{tpl.name}</span>
            <span className="ml-2 text-xs text-muted-foreground">
              ({tpl.template_code})
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
