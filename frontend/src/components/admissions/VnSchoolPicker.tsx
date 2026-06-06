"use client"

/**
 * VnSchoolPicker — Async autocomplete combobox for VnSchool entries.
 *
 * Q9 #07 Phase D.1 candidate FE component. Searches `vn_school` via
 * GET /api/v2/vn-school/search (diacritic-insensitive). Emits picked
 * school via onChange (full object with id, name, level, current_kv).
 *
 * Fallback: user can type free text. If they don't pick a school from
 * dropdown, only `school_name` is set (school_id stays null) — engine
 * resolve_kv() will skip this entry, candidate KV resolves via other
 * entries or commune fallback.
 */
import * as React from "react"
import { Check, ChevronsUpDown, Loader2, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { useVnSchoolSearch } from "@/lib/hooks/use-vn-school-search"
import type { VnSchoolSearchItem } from "@/lib/api/vn-school"

export interface VnSchoolPickerValue {
  school_id: number | null
  school_name: string
  level: string | null
  current_kv: string | null
}

interface VnSchoolPickerProps {
  value: VnSchoolPickerValue
  onChange: (value: VnSchoolPickerValue) => void
  /** Pre-filter results by school level (THPT/THCS/etc.). Optional. */
  levelFilter?: string
  placeholder?: string
  disabled?: boolean
  className?: string
}

export function VnSchoolPicker({
  value,
  onChange,
  levelFilter,
  placeholder = "Tìm trường (gõ tối thiểu 2 ký tự)...",
  disabled = false,
  className,
}: VnSchoolPickerProps) {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState("")
  const [debouncedQuery, setDebouncedQuery] = React.useState("")
  // Display-only KV of the school picked in THIS session. The form schema
  // (academicRecordSchema) has NO current_kv field — KV is engine-resolved at
  // submit — so the AcademicHistoryTab parent always feeds `value.current_kv =
  // null` back. Without this, the "KV hiện tại" badge could never render after
  // a pick, even though the search API returns the school's current_kv. We keep
  // {id, kv} so the badge only shows for the school currently selected (no stale
  // KV if the selection changes). Falls back to value.current_kv when a parent
  // does supply one (e.g. the unit tests).
  const [pickedSchool, setPickedSchool] = React.useState<{
    id: number
    kv: string | null
  } | null>(null)

  // Debounce search query (300ms)
  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300)
    return () => clearTimeout(t)
  }, [query])

  const { data, isLoading } = useVnSchoolSearch({
    q: debouncedQuery,
    level: levelFilter,
    limit: 20,
  })

  const handleSelect = (school: VnSchoolSearchItem) => {
    setPickedSchool({ id: school.id, kv: school.current_kv })
    onChange({
      school_id: school.id,
      school_name: school.name,
      level: school.level,
      current_kv: school.current_kv,
    })
    setOpen(false)
  }

  const handleManualClear = (e: React.MouseEvent) => {
    e.stopPropagation()
    setPickedSchool(null)
    onChange({
      school_id: null,
      school_name: "",
      level: null,
      current_kv: null,
    })
    setQuery("")
  }

  // KV to display in the badge: the parent's value.current_kv if present, else
  // the in-session pick — but only when it matches the currently selected school
  // (guards against showing a previous school's KV after the selection changes).
  const displayKv =
    value.current_kv ??
    (pickedSchool && pickedSchool.id === value.school_id ? pickedSchool.kv : null)

  const displayLabel = value.school_name || placeholder

  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex gap-1 items-stretch">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            aria-label="Chọn trường THPT từ danh mục"
            className="flex-1 justify-between font-normal h-11 md:h-9"
            disabled={disabled}
          >
            <span
              className={cn(
                "truncate",
                !value.school_name && "text-muted-foreground"
              )}
            >
              {displayLabel}
            </span>
            <ChevronsUpDown className="h-4 w-4 opacity-50 ml-2 shrink-0" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[var(--radix-popover-trigger-width)] p-0"
          align="start"
        >
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="Gõ tên trường (không cần dấu)..."
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {isLoading && (
                <div className="flex items-center justify-center py-4 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang tìm...
                </div>
              )}
              {!isLoading && query.length < 2 && (
                <CommandEmpty>Gõ tối thiểu 2 ký tự</CommandEmpty>
              )}
              {!isLoading && query.length >= 2 && data?.items.length === 0 && (
                <CommandEmpty>
                  Không tìm thấy trường nào. Bạn có thể gõ tên trường thủ công
                  vào ô bên dưới nếu chưa có trong hệ thống.
                </CommandEmpty>
              )}
              {!isLoading && data && data.items.length > 0 && (
                <CommandGroup>
                  {data.items.map((school) => (
                    <CommandItem
                      key={school.id}
                      value={`${school.id}`}
                      onSelect={() => handleSelect(school)}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4",
                          value.school_id === school.id
                            ? "opacity-100"
                            : "opacity-0"
                        )}
                      />
                      <div className="flex flex-col flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium">
                            {school.name}
                          </span>
                          {school.is_dtnt && (
                            <span className="text-xs px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded">
                              DTNT
                            </span>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground truncate">
                          {[school.district, school.province]
                            .filter(Boolean)
                            .join(" — ")}
                          {school.current_kv && (
                            <span className="ml-2 text-info-700 font-medium">
                              [{school.current_kv}]
                            </span>
                          )}
                        </span>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
              {!isLoading && data && data.total > data.items.length && (
                <div className="px-3 py-2 text-xs text-muted-foreground border-t">
                  Hiển thị {data.items.length}/{data.total} kết quả. Gõ thêm ký
                  tự để thu hẹp tìm kiếm.
                </div>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Clear button — tách khỏi combobox trigger (Commit 5 A11y) để
          tránh nested interactive. Button riêng, accessible name rõ,
          keyboard tab focus được. */}
      {value.school_id && !disabled && (
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={handleManualClear}
          aria-label="Bỏ chọn trường"
          className="shrink-0 text-muted-foreground hover:text-destructive size-11 md:size-9"
        >
          <X className="h-4 w-4" />
        </Button>
      )}
      </div>

      {/* Selected school metadata badge */}
      {value.school_id && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground px-1">
          <span>
            ✓ Đã chọn từ danh mục
            {value.level && (
              <span className="ml-2 font-medium">{value.level}</span>
            )}
            {displayKv && (
              <span className="ml-2 text-info-700 font-medium">
                KV hiện tại: {displayKv}
              </span>
            )}
          </span>
        </div>
      )}
    </div>
  )
}
