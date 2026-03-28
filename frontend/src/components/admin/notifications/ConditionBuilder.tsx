// NOTE: Currently unused after NotificationRuleForm was removed. Retained for potential
// future use in compound condition UI (AND/OR groups).

// src/components/admin/notifications/ConditionBuilder.tsx
/**
 * ✅ PHASE 3.2: Visual Condition Builder Component
 *
 * Replaces JSON textarea with visual IF-THEN builder for notification rule conditions.
 * Features:
 * - Nested AND/OR groups
 * - Field autocomplete from payload schema
 * - Operator selection (eq, ne, gt, gte, lt, lte, in, not_in, contains)
 * - Visual nesting and grouping
 * - Add/remove conditions dynamically
 *
 * Condition Structure:
 * Simple: {"field": "lead.status", "operator": "eq", "value": "new"}
 * Compound: {"operator": "and", "conditions": [...]}
 */
"use client";

import { useState } from "react";
import { Plus, Trash2, GripVertical } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";

// Condition types
type SimpleCondition = {
  field: string;
  operator: string;
  value: unknown;
};

type CompoundCondition = {
  operator: "and" | "or";
  conditions: Condition[];
};

export type Condition = SimpleCondition | CompoundCondition | null;

// Operators by data type
const OPERATORS = {
  string: [
    { value: "eq", label: "equals" },
    { value: "ne", label: "not equals" },
    { value: "contains", label: "contains" },
    { value: "in", label: "in list" },
    { value: "not_in", label: "not in list" },
  ],
  number: [
    { value: "eq", label: "equals" },
    { value: "ne", label: "not equals" },
    { value: "gt", label: "greater than" },
    { value: "gte", label: "greater or equal" },
    { value: "lt", label: "less than" },
    { value: "lte", label: "less or equal" },
  ],
  boolean: [
    { value: "eq", label: "is" },
    { value: "ne", label: "is not" },
  ],
};

// =============================================================================
// ✅ FIX: Edge Case #5 - Frontend Validation Helpers
// =============================================================================

/**
 * Validate a condition tree to ensure all fields have values.
 * Returns array of validation error messages.
 *
 * Usage in form submit:
 *   const errors = validateCondition(condition);
 *   if (errors.length > 0) {
 *     toast.error(errors.join(", "));
 *     return;
 *   }
 */
export function validateCondition(condition: Condition): string[] {
  const errors: string[] = [];

  if (!condition) {
    return errors;
  }

  // Check if it's a compound condition
  if ("conditions" in condition && "operator" in condition) {
    const compound = condition as CompoundCondition;

    // Compound condition must have at least one sub-condition
    if (!compound.conditions || compound.conditions.length === 0) {
      errors.push("Condition group cannot be empty. Add at least one condition or remove the group.");
    } else {
      // Recursively validate each sub-condition
      compound.conditions.forEach((subCond, index) => {
        const subErrors = validateCondition(subCond);
        subErrors.forEach(err => {
          errors.push(`Condition ${index + 1}: ${err}`);
        });
      });
    }
  } else {
    // Simple condition validation
    const simple = condition as SimpleCondition;

    if (!simple.field || simple.field.trim() === "") {
      errors.push("Field name is required");
    }

    if (!simple.operator || simple.operator.trim() === "") {
      errors.push("Operator is required");
    }

    if (simple.value === null || simple.value === undefined || simple.value === "") {
      // Allow empty for certain operators (like is_null)
      if (simple.operator !== "is_null" && simple.operator !== "is_not_null") {
        errors.push("Value is required");
      }
    }
  }

  return errors;
}

// Available fields by event type (can be expanded)
const FIELD_SCHEMAS: Record<string, { value: string; label: string; type: string }[]> = {
  LEAD_ASSIGNED: [
    { value: "lead.status", label: "Lead Status", type: "string" },
    { value: "lead.priority", label: "Lead Priority", type: "number" },
    { value: "lead.source", label: "Lead Source", type: "string" },
    { value: "officer.role", label: "Officer Role", type: "string" },
  ],
  LEAD_STATUS_UPDATED: [
    { value: "lead.status", label: "Lead Status", type: "string" },
    { value: "lead.old_status", label: "Previous Status", type: "string" },
    { value: "lead.priority", label: "Lead Priority", type: "number" },
  ],
  CONSULTATION_SCHEDULED: [
    { value: "consultation.type", label: "Consultation Type", type: "string" },
    { value: "consultation.is_online", label: "Is Online", type: "boolean" },
  ],
  APPLICATION_SUBMITTED: [
    { value: "application.status", label: "Application Status", type: "string" },
    { value: "application.program", label: "Program", type: "string" },
  ],
  // Add more event schemas as needed
};

interface ConditionBuilderProps {
  value: Condition;
  onChange: (condition: Condition) => void;
  eventType?: string;
}

export function ConditionBuilder({ value, onChange, eventType }: ConditionBuilderProps) {
  const [showBuilder, setShowBuilder] = useState(!!value);

  const handleToggle = () => {
    if (showBuilder) {
      onChange(null);
      setShowBuilder(false);
    } else {
      onChange({
        operator: "and",
        conditions: [],
      } as CompoundCondition);
      setShowBuilder(true);
    }
  };

  if (!showBuilder) {
    return (
      <div className="space-y-2">
        <Button type="button" variant="outline" onClick={handleToggle}>
          <Plus className="mr-2 h-4 w-4" />
          Add Activation Conditions
        </Button>
        <p className="text-sm text-muted-foreground">
          Optional: Rule will always activate if no conditions are set
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">Activation Conditions</h4>
        <Button type="button" variant="ghost" size="sm" onClick={handleToggle}>
          <Trash2 className="mr-2 h-4 w-4" />
          Remove All Conditions
        </Button>
      </div>

      <Card className="p-4">
        <ConditionGroup
          condition={value as CompoundCondition}
          onChange={onChange}
          onRemove={() => onChange(null)}
          eventType={eventType}
          isRoot
        />
      </Card>

      <p className="text-xs text-muted-foreground">
        Rule will only activate when these conditions are met
      </p>
    </div>
  );
}

interface ConditionGroupProps {
  condition: CompoundCondition | null;
  onChange: (condition: Condition) => void;
  onRemove: () => void;
  eventType?: string;
  isRoot?: boolean;
  depth?: number;
}

function ConditionGroup({
  condition,
  onChange,
  onRemove,
  eventType,
  isRoot = false,
  depth = 0,
}: ConditionGroupProps) {
  const operator = condition?.operator || "and";
  const conditions = condition?.conditions || [];

  const handleOperatorChange = (newOperator: "and" | "or") => {
    onChange({
      operator: newOperator,
      conditions: conditions,
    });
  };

  const handleAddSimpleCondition = () => {
    const newCondition: SimpleCondition = {
      field: "",
      operator: "eq",
      value: "",
    };
    onChange({
      operator,
      conditions: [...conditions, newCondition],
    });
  };

  const handleAddGroup = () => {
    const newGroup: CompoundCondition = {
      operator: "and",
      conditions: [],
    };
    onChange({
      operator,
      conditions: [...conditions, newGroup],
    });
  };

  const handleConditionChange = (index: number, newCondition: Condition) => {
    const newConditions = [...conditions];
    newConditions[index] = newCondition as SimpleCondition | CompoundCondition;
    onChange({
      operator,
      conditions: newConditions,
    });
  };

  const handleConditionRemove = (index: number) => {
    const newConditions = conditions.filter((_, i) => i !== index);
    if (newConditions.length === 0 && !isRoot) {
      onRemove();
    } else {
      onChange({
        operator,
        conditions: newConditions,
      });
    }
  };

  const isCompoundCondition = (cond: unknown): cond is CompoundCondition => {
    return Boolean(cond && typeof cond === "object" && "operator" in cond && "conditions" in cond);
  };

  return (
    <div className={`space-y-3 ${depth > 0 ? "pl-4 border-l-2 border-muted" : ""}`}>
      {/* Operator selector */}
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">Match</span>
        <Select value={operator} onValueChange={handleOperatorChange}>
          <SelectTrigger className="w-24">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="and">ALL</SelectItem>
            <SelectItem value="or">ANY</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground">of the following:</span>
        {!isRoot && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onRemove}
            className="ml-auto"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Conditions */}
      <div className="space-y-2">
        {conditions.map((cond, index) => {
          // Skip null conditions
          if (!cond) return null;

          return isCompoundCondition(cond) ? (
            <ConditionGroup
              key={index}
              condition={cond}
              onChange={(newCond) => handleConditionChange(index, newCond)}
              onRemove={() => handleConditionRemove(index)}
              eventType={eventType}
              depth={depth + 1}
            />
          ) : (
            <SimpleConditionRow
              key={index}
              condition={cond as SimpleCondition}
              onChange={(newCond) => handleConditionChange(index, newCond)}
              onRemove={() => handleConditionRemove(index)}
              eventType={eventType}
            />
          );
        })}
      </div>

      {/* Add buttons */}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleAddSimpleCondition}
        >
          <Plus className="mr-2 h-4 w-4" />
          Add Condition
        </Button>
        {depth < 2 && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleAddGroup}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Group
          </Button>
        )}
      </div>
    </div>
  );
}

interface SimpleConditionRowProps {
  condition: SimpleCondition;
  onChange: (condition: SimpleCondition) => void;
  onRemove: () => void;
  eventType?: string;
}

function SimpleConditionRow({
  condition,
  onChange,
  onRemove,
  eventType,
}: SimpleConditionRowProps) {
  const fields = eventType && FIELD_SCHEMAS[eventType] ? FIELD_SCHEMAS[eventType] : [];
  const selectedField = fields.find((f) => f.value === condition.field);
  const fieldType = selectedField?.type || "string";
  const operators = OPERATORS[fieldType as keyof typeof OPERATORS] || OPERATORS.string;

  const handleFieldChange = (field: string) => {
    onChange({ ...condition, field, value: "" });
  };

  const handleOperatorChange = (operator: string) => {
    onChange({ ...condition, operator });
  };

  const handleValueChange = (value: unknown) => {
    onChange({ ...condition, value });
  };

  return (
    <div className="flex items-center gap-2 p-2 border rounded-md bg-muted/50">
      <GripVertical className="h-4 w-4 text-muted-foreground" />

      {/* Field */}
      {fields.length > 0 ? (
        <Select value={condition.field} onValueChange={handleFieldChange}>
          <SelectTrigger className="w-[200px]">
            <SelectValue placeholder="Select field..." />
          </SelectTrigger>
          <SelectContent>
            {fields.map((field) => (
              <SelectItem key={field.value} value={field.value}>
                {field.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          placeholder="e.g., lead.status"
          value={condition.field}
          onChange={(e) => handleFieldChange(e.target.value)}
          className="w-[200px]"
        />
      )}

      {/* Operator */}
      <Select value={condition.operator} onValueChange={handleOperatorChange}>
        <SelectTrigger className="w-[150px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {operators.map((op) => (
            <SelectItem key={op.value} value={op.value}>
              {op.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Value */}
      {fieldType === "boolean" ? (
        <Select
          value={String(condition.value)}
          onValueChange={(v) => handleValueChange(v === "true")}
        >
          <SelectTrigger className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true">True</SelectItem>
            <SelectItem value="false">False</SelectItem>
          </SelectContent>
        </Select>
      ) : fieldType === "number" ? (
        <Input
          type="number"
          placeholder="Value"
          value={condition.value as number | string | undefined}
          onChange={(e) => handleValueChange(Number(e.target.value))}
          className="w-[120px]"
        />
      ) : condition.operator === "in" || condition.operator === "not_in" ? (
        <Input
          placeholder="value1, value2, value3"
          value={Array.isArray(condition.value) ? condition.value.join(", ") : (condition.value as string | undefined)}
          onChange={(e) =>
            handleValueChange(e.target.value.split(",").map((v) => v.trim()))
          }
          className="flex-1"
        />
      ) : (
        <Input
          placeholder="Value"
          value={condition.value as string | undefined}
          onChange={(e) => handleValueChange(e.target.value)}
          className="flex-1"
        />
      )}

      {/* Remove button */}
      <Button type="button" variant="ghost" size="icon" onClick={onRemove} aria-label="Xóa điều kiện">
        <Trash2 className="h-4 w-4 text-destructive" />
      </Button>
    </div>
  );
}
