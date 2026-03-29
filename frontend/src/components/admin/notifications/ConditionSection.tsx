// src/components/admin/notifications/ConditionSection.tsx
/**
 * Step 1 sub-component: Condition builder UI (toggle + simple/compound).
 * Extracted from NotificationRuleWizard for modularity.
 *
 * Receives all condition state and callbacks as props (no react-hook-form dependency).
 */
"use client";

import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";

// ============================================
// TYPES
// ============================================

export interface ConditionSectionProps {
  conditionEnabled: boolean;
  onConditionEnabledChange: (enabled: boolean) => void;
  conditionField: string;
  onConditionFieldChange: (field: string) => void;
  conditionOperator: string;
  onConditionOperatorChange: (operator: string) => void;
  conditionValue: string;
  onConditionValueChange: (value: string) => void;
  isCompoundCondition: boolean;
  onIsCompoundConditionChange: (isCompound: boolean) => void;
  conditionData: Record<string, unknown> | null;
  updateCondition: (field: string, operator: string, value: string) => void;
  selectedEventMetadata: {
    condition_fields?: Array<{
      path: string;
      type: string;
      description: string;
      operators: string[];
    }>;
  } | null | undefined;
}

// ============================================
// CONSTANTS
// ============================================

/** Canonical operator labels (Vietnamese) */
const OPERATOR_LABELS: Record<string, string> = {
  eq: "Bằng (=)",
  ne: "Khác (≠)",
  gt: "Lớn hơn (>)",
  gte: "Lớn hơn hoặc bằng (≥)",
  lt: "Nhỏ hơn (<)",
  lte: "Nhỏ hơn hoặc bằng (≤)",
  in: "Trong danh sách",
  not_in: "Không trong danh sách",
  contains: "Chứa",
};

// ============================================
// COMPONENT
// ============================================

export function ConditionSection({
  conditionEnabled,
  onConditionEnabledChange,
  conditionField,
  onConditionFieldChange,
  conditionOperator,
  onConditionOperatorChange,
  conditionValue,
  onConditionValueChange,
  isCompoundCondition,
  conditionData,
  updateCondition,
  selectedEventMetadata,
}: ConditionSectionProps) {
  return (
    <div className="space-y-4">
      {/* Enable/Disable Condition */}
      <div className="flex items-center justify-between rounded-lg border p-4">
        <div className="space-y-0.5">
          <p className="text-sm font-medium">Bật điều kiện lọc</p>
          <p className="text-xs text-muted-foreground">
            Chỉ gửi thông báo khi đáp ứng điều kiện
          </p>
        </div>
        <Switch
          checked={conditionEnabled}
          onCheckedChange={onConditionEnabledChange}
        />
      </div>

      {/* Visual Condition Builder */}
      {conditionEnabled && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Thiết lập điều kiện</CardTitle>
            <CardDescription>
              Chỉ gửi thông báo khi thỏa mãn điều kiện dưới đây
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {isCompoundCondition ? (
              <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 space-y-2">
                <p className="text-sm font-medium text-yellow-800">
                  Điều kiện phức hợp (AND/OR)
                </p>
                <p className="text-xs text-yellow-700">
                  Rule này có điều kiện phức hợp. Chỉnh sửa qua API.
                  Nếu bạn tắt điều kiện, dữ liệu cũ sẽ bị mất.
                </p>
                <pre className="text-xs p-2 bg-white rounded border overflow-auto max-h-32">
                  {JSON.stringify(conditionData, null, 2)}
                </pre>
              </div>
            ) : (
              <>
                {/* Condition Field */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">Trường dữ liệu</label>
                  <Select
                    value={conditionField}
                    onValueChange={(value) => {
                      onConditionFieldChange(value);
                      updateCondition(value, conditionOperator, conditionValue);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Chọn trường..." />
                    </SelectTrigger>
                    <SelectContent>
                      {selectedEventMetadata?.condition_fields?.map((cf) => (
                        <SelectItem key={cf.path} value={cf.path}>{cf.description}</SelectItem>
                      )) ?? (
                        <SelectItem value="" disabled>Chọn sự kiện trước</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>

                {/* Condition Operator */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">Phép so sánh</label>
                  <Select
                    value={conditionOperator}
                    onValueChange={(value) => {
                      onConditionOperatorChange(value);
                      updateCondition(conditionField, value, conditionValue);
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(() => {
                        const fieldMeta = selectedEventMetadata?.condition_fields?.find(
                          (cf) => cf.path === conditionField
                        );
                        const ops = fieldMeta?.operators ?? ["eq", "ne"];
                        return ops.map((op: string) => (
                          <SelectItem key={op} value={op}>
                            {OPERATOR_LABELS[op] ?? op}
                          </SelectItem>
                        ));
                      })()}
                    </SelectContent>
                  </Select>
                </div>

                {/* Condition Value */}
                <div className="space-y-2">
                  <label className="text-sm font-medium">Giá trị</label>
                  {(() => {
                    const fieldMeta = selectedEventMetadata?.condition_fields?.find(
                      (cf) => cf.path === conditionField
                    );
                    const fieldType = fieldMeta?.type ?? "string";

                    if (fieldType === "boolean") {
                      return (
                        <Select
                          value={conditionValue}
                          onValueChange={(value) => {
                            onConditionValueChange(value);
                            updateCondition(conditionField, conditionOperator, value);
                          }}
                        >
                          <SelectTrigger>
                            <SelectValue placeholder="Chọn giá trị..." />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="true">Có (true)</SelectItem>
                            <SelectItem value="false">Không (false)</SelectItem>
                          </SelectContent>
                        </Select>
                      );
                    }

                    const isListOp = conditionOperator === "in" || conditionOperator === "not_in";

                    return (
                      <Input
                        type={!isListOp && (fieldType === "integer" || fieldType === "float") ? "number" : "text"}
                        placeholder={isListOp ? "Nhập danh sách phân cách bằng dấu phẩy (VD: admin, manager)" : "Nhập giá trị..."}
                        value={conditionValue}
                        onChange={(e) => {
                          onConditionValueChange(e.target.value);
                          updateCondition(conditionField, conditionOperator, e.target.value);
                        }}
                      />
                    );
                  })()}
                </div>

                {/* Preview */}
                {conditionField && conditionValue && (
                  <div className="bg-info-50 border-l-2 border-info-400 px-3 py-2 rounded">
                    <p className="text-xs font-medium text-info-900 mb-1">
                      Điều kiện hiện tại:
                    </p>
                    <code className="text-xs text-info-700">
                      {conditionField} {conditionOperator} &ldquo;{conditionValue}&rdquo;
                    </code>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default ConditionSection;
