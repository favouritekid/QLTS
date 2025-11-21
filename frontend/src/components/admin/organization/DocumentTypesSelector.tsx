// =====================================================================
// DOCUMENT TYPES SELECTOR COMPONENT
// File: components/admin/organization/DocumentTypesSelector.tsx
// =====================================================================

"use client";

import { useState } from "react";
import { Check, ChevronsUpDown, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useDocumentTypes } from "@/hooks/useOrganization";

// =====================================================================
// TYPES
// =====================================================================

interface RequiredDocument {
  code: string;
  label: string;
}

interface DocumentTypesSelectorProps {
  value: RequiredDocument[];
  onChange: (documents: RequiredDocument[]) => void;
  disabled?: boolean;
}

// =====================================================================
// MAIN COMPONENT
// =====================================================================

export function DocumentTypesSelector({
  value = [],
  onChange,
  disabled = false,
}: DocumentTypesSelectorProps) {
  const [open, setOpen] = useState(false);

  // Fetch available document types
  const { data: documentTypes = [], isLoading } = useDocumentTypes(true);

  // Get codes of already selected documents
  const selectedCodes = value.map((doc) => doc.code);

  // Handle adding a document
  const handleAddDocument = (code: string, name: string) => {
    // Check if already selected
    if (selectedCodes.includes(code)) return;

    // Add new document
    onChange([...value, { code, label: name }]);
    setOpen(false);
  };

  // Handle removing a document
  const handleRemoveDocument = (code: string) => {
    onChange(value.filter((doc) => doc.code !== code));
  };

  return (
    <div className="space-y-2">
      {/* Popover to add documents */}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            role="combobox"
            aria-expanded={open}
            disabled={disabled || isLoading}
            className="w-full justify-between"
          >
            <span className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              {isLoading ? "Đang tải..." : "Thêm hồ sơ bắt buộc"}
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[400px] p-0" align="start">
          <Command>
            <CommandInput placeholder="Tìm kiếm loại hồ sơ..." />
            <CommandEmpty>Không tìm thấy loại hồ sơ nào.</CommandEmpty>
            <CommandGroup className="max-h-64 overflow-auto">
              {documentTypes.map((docType) => {
                const isSelected = selectedCodes.includes(docType.code);

                return (
                  <CommandItem
                    key={docType.id}
                    value={docType.name}
                    onSelect={() => {
                      if (!isSelected) {
                        handleAddDocument(docType.code, docType.name);
                      }
                    }}
                    disabled={isSelected}
                    className={cn(
                      "flex cursor-pointer items-center justify-between",
                      isSelected && "cursor-not-allowed opacity-50"
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Check className={cn("h-4 w-4", isSelected ? "opacity-100" : "opacity-0")} />
                      <div>
                        <div className="font-medium">{docType.name}</div>
                        {docType.description && (
                          <div className="text-muted-foreground text-xs">{docType.description}</div>
                        )}
                      </div>
                    </div>
                    <code className="bg-muted rounded px-2 py-1 text-xs">{docType.code}</code>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Display selected documents */}
      {value.length === 0 ? (
        <div className="text-muted-foreground rounded border border-dashed py-3 text-center text-xs">
          Chưa có hồ sơ bắt buộc. Nhấn &quot;Thêm hồ sơ bắt buộc&quot; để chọn.
        </div>
      ) : (
        <div className="space-y-1.5">
          {value.map((doc) => {
            // Find full document info
            const docType = documentTypes.find((dt) => dt.code === doc.code);

            return (
              <div
                key={doc.code}
                className="bg-muted/30 hover:bg-muted/50 flex items-center justify-between rounded-md border p-2 transition-colors"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <Badge variant="outline" className="shrink-0 text-xs">
                    {doc.code}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{doc.label}</div>
                    {docType?.description && (
                      <div className="text-muted-foreground truncate text-xs">
                        {docType.description}
                      </div>
                    )}
                  </div>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveDocument(doc.code)}
                  disabled={disabled}
                  className="text-destructive hover:text-destructive hover:bg-destructive/10 h-7 w-7 shrink-0 p-0"
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
            );
          })}
        </div>
      )}

      {/* Summary */}
      {value.length > 0 && (
        <div className="text-muted-foreground text-xs">
          Đã chọn {value.length} loại hồ sơ bắt buộc
        </div>
      )}
    </div>
  );
}
