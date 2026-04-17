"use client";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Bell, MessageSquare } from "lucide-react";
import type { Control } from "react-hook-form";
import VariablePickerPanel from "./VariablePickerPanel";

// Notification types with colors
const NOTIFICATION_TYPES = [
  { value: "info", label: "Thông tin", color: "bg-info-100 text-info-800", description: "Thông báo mang tính thông tin" },
  { value: "success", label: "Thành công", color: "bg-success-100 text-success-800", description: "Thông báo hành động thành công" },
  { value: "warning", label: "Cảnh báo", color: "bg-warning-100 text-warning-800", description: "Thông báo cần chú ý" },
  { value: "error", label: "Lỗi", color: "bg-error-100 text-error-800", description: "Thông báo lỗi hoặc thất bại" },
];

// Helper tooltip (inline, small)
function HelpTooltip({ content }: { content: string }) {
  return (
    <span className="inline-flex items-center" title={content}>
      <span className="ml-1 text-muted-foreground text-xs cursor-help">&#9432;</span>
    </span>
  );
}

interface Variable {
  variable: string;
  label: string;
  description: string;
}

interface DefaultContentSectionProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Control is invariant; shared component must accept any form shape
  formControl: Control<any>;
  availableVariables: Variable[];
  onInsertVariable: (field: "title_template" | "message_template", variable: string) => void;
  titleTemplate: string;
  messageTemplate: string;
  linkStrategy?: string | null; // PR2: code-owned link pattern from catalog
}

export default function DefaultContentSection({
  formControl,
  availableVariables,
  onInsertVariable,
  titleTemplate,
  messageTemplate,
  linkStrategy,
}: DefaultContentSectionProps) {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold mb-1 flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-primary" />
          Bước 2: Nội dung mặc định
          <HelpTooltip content="Nhấp vào biến phía dưới để chèn vào nội dung. Biến sẽ tự động thay thế khi gửi thông báo." />
        </h3>
        <p className="text-sm text-muted-foreground">
          Soạn tiêu đề và nội dung thông báo
        </p>
      </div>

      {/* Variable Picker */}
      <VariablePickerPanel
        variables={availableVariables}
        onInsert={(variable, target) => onInsertVariable(target, variable)}
      />

      {/* Title Template */}
      <FormField
        control={formControl}
        name="title_template"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Tiêu đề thông báo</FormLabel>
            <FormControl>
              <Input
                id="title_template"
                placeholder="VD: Lead mới: $lead_name"
                {...field}
              />
            </FormControl>
            <FormDescription>
              Tiêu đề ngắn gọn, súc tích. Click biến phía trên để chèn tự động.
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />

      {/* Message Template */}
      <FormField
        control={formControl}
        name="message_template"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Nội dung thông báo</FormLabel>
            <FormControl>
              <Textarea
                id="message_template"
                placeholder="VD: Lead $lead_name ($lead_phone) đã được phân công cho bạn."
                rows={4}
                {...field}
              />
            </FormControl>
            <FormDescription>
              Mô tả chi tiết nội dung thông báo. Click biến phía trên để chèn tự động.
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />

      <Separator />

      {/* Notification Type */}
      <FormField
        control={formControl}
        name="notification_type"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Loại thông báo</FormLabel>
            <Select onValueChange={field.onChange} value={field.value}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {NOTIFICATION_TYPES.map((type) => (
                  <SelectItem key={type.value} value={type.value}>
                    <div className="flex items-center gap-2">
                      <Badge className={type.color} variant="secondary">
                        {type.label}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        - {type.description}
                      </span>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormDescription>
              Kiểu hiển thị (ảnh hưởng đến biểu tượng và màu sắc thông báo)
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />

      {/* Link Strategy — read-only, code-owned (PR2) */}
      <div className="space-y-1.5">
        <p className="text-sm font-medium">Liên kết thông báo</p>
        {linkStrategy ? (
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="font-mono text-xs">
              {linkStrategy}
            </Badge>
            <span className="text-xs text-muted-foreground">
              (tự động theo sự kiện)
            </span>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Sự kiện này không có liên kết đi kèm.
          </p>
        )}
      </div>

      {/* Preview */}
      {(titleTemplate || messageTemplate) && (
        <Card className="bg-muted/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Bell className="h-4 w-4" />
              Xem trước thông báo
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="bg-background rounded-lg border p-4 space-y-2">
              {titleTemplate && (
                <p className="font-semibold text-sm">{titleTemplate}</p>
              )}
              {messageTemplate && (
                <p className="text-sm text-muted-foreground">{messageTemplate}</p>
              )}
              <p className="text-xs text-muted-foreground/70">Vừa xong</p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
