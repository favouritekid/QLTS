"use client";

import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import type { RecipientKind, ExternalResolverOption } from "./wizard-types";
import type { ResolverTypeOption } from "@/types/api.types";

interface ResolverPickerProps {
  recipientKind: RecipientKind;
  value: string;
  onChange: (value: string) => void;
  resolverOptions: ResolverTypeOption[];
  externalResolverOptions: ExternalResolverOption[];
}

export default function ResolverPicker({
  recipientKind,
  value,
  onChange,
  resolverOptions,
  externalResolverOptions,
}: ResolverPickerProps) {
  const options =
    recipientKind === "internal" ? resolverOptions : externalResolverOptions;

  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground">
        Gửi cho ai?
      </label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="mt-1">
          <SelectValue placeholder="Chọn người nhận..." />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
