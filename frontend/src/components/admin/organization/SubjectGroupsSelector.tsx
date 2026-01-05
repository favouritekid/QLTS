// src/components/admin/organization/SubjectGroupsSelector.tsx
"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { Search, X, ChevronDown, BookOpen } from "lucide-react";
import { configApi, type SubjectGroup } from "@/lib/api/config";
import { cn } from "@/lib/utils";

interface SubjectGroupsSelectorProps {
  value: string; // Comma-separated string "A00, A01, D01"
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function SubjectGroupsSelector({
  value,
  onChange,
  disabled = false,
  placeholder = "Chọn tổ hợp môn...",
}: SubjectGroupsSelectorProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");

  // Fetch subject groups from API
  const { data: subjectGroups, isLoading } = useQuery({
    queryKey: ["subject-groups"],
    queryFn: () => configApi.getSubjectGroups(),
    staleTime: 1000 * 60 * 10, // Cache 10 minutes
  });

  // Parse selected codes from comma-separated string
  const selectedCodes = useMemo(() => {
    if (!value) return [];
    return value.split(",").map((s) => s.trim()).filter(Boolean);
  }, [value]);

  // Filter groups by search
  const filteredGroups = useMemo(() => {
    if (!subjectGroups) return [];
    if (!search) return subjectGroups;
    const searchLower = search.toLowerCase();
    return subjectGroups.filter(
      (g) =>
        g.code.toLowerCase().includes(searchLower) ||
        g.name.toLowerCase().includes(searchLower)
    );
  }, [subjectGroups, search]);

  // Group by prefix (A, B, C, D, etc.)
  const groupedByPrefix = useMemo(() => {
    const groups: Record<string, SubjectGroup[]> = {};
    for (const group of filteredGroups) {
      const prefix = group.code.charAt(0);
      if (!groups[prefix]) groups[prefix] = [];
      groups[prefix].push(group);
    }
    return groups;
  }, [filteredGroups]);

  // Toggle selection
  const toggleGroup = (code: string) => {
    const newCodes = selectedCodes.includes(code)
      ? selectedCodes.filter((c) => c !== code)
      : [...selectedCodes, code];
    onChange(newCodes.join(", "));
  };

  // Remove single selection
  const removeCode = (code: string) => {
    const newCodes = selectedCodes.filter((c) => c !== code);
    onChange(newCodes.join(", "));
  };

  // Clear all
  const clearAll = () => {
    onChange("");
  };

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            disabled={disabled}
            className="w-full justify-between"
          >
            <span className="truncate">
              {selectedCodes.length > 0
                ? `Đã chọn ${selectedCodes.length} tổ hợp`
                : placeholder}
            </span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[400px] p-0" align="start">
          <div className="p-2 border-b">
            <div className="flex items-center gap-2">
              <Search className="h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Tìm mã tổ hợp (VD: A00, D01)..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="border-0 focus-visible:ring-0 h-8"
              />
            </div>
          </div>

          {isLoading ? (
            <div className="p-4 space-y-2">
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-full" />
              <Skeleton className="h-6 w-3/4" />
            </div>
          ) : (
            <div className="max-h-[300px] overflow-y-auto p-2">
              {Object.keys(groupedByPrefix).length === 0 ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  Không tìm thấy tổ hợp môn
                </div>
              ) : (
                Object.entries(groupedByPrefix)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([prefix, groups]) => (
                    <div key={prefix} className="mb-3">
                      <div className="text-xs font-semibold text-muted-foreground uppercase mb-1 px-2">
                        Khối {prefix}
                      </div>
                      <div className="space-y-1">
                        {groups.map((group) => {
                          const isSelected = selectedCodes.includes(group.code);
                          return (
                            <div
                              key={group.code}
                              onClick={() => toggleGroup(group.code)}
                              className={cn(
                                "flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer hover:bg-muted/50 transition-colors",
                                isSelected && "bg-primary/10"
                              )}
                            >
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={() => toggleGroup(group.code)}
                                className="pointer-events-none"
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium text-sm">{group.code}</span>
                                  <span className="text-xs text-muted-foreground truncate">
                                    {group.name}
                                  </span>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))
              )}
            </div>
          )}

          {selectedCodes.length > 0 && (
            <div className="border-t p-2 flex justify-between items-center">
              <span className="text-xs text-muted-foreground">
                {selectedCodes.length} đã chọn
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearAll}
                className="h-7 text-xs"
              >
                Xóa tất cả
              </Button>
            </div>
          )}
        </PopoverContent>
      </Popover>

      {/* Display selected badges */}
      {selectedCodes.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selectedCodes.map((code) => (
            <Badge
              key={code}
              variant="secondary"
              className="gap-1 pr-1"
            >
              <BookOpen className="h-3 w-3" />
              {code}
              {!disabled && (
                <button
                  type="button"
                  onClick={() => removeCode(code)}
                  className="ml-1 rounded-full hover:bg-muted p-0.5"
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
