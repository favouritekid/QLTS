/**
 * CommunePicker — chọn xã/phường từ bảng xã → KV (dòng còn hiệu lực).
 *
 * Dùng lại API danh mục xã có sẵn `GET /api/v2/admin/vn-locality/communes`
 * (`useCommunes`, active_only) — không thêm endpoint. Mỗi dòng mang `area_code`
 * hiện hành nên form trường hiển thị được "KV gợi ý" ngay khi chọn. KV gợi ý chỉ
 * để Admin XEM; dòng KV của trường chỉ ghi khi Admin bấm xác nhận trong mục
 * "Quản lý KV" (BE chép KV của xã lúc ấy).
 */

"use client"

import { useEffect, useState } from "react"
import { Check, ChevronsUpDown, Loader2, X } from "lucide-react"

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

import { useCommunes } from "@/lib/hooks/useCommuneKvAdmin"
import { cn } from "@/lib/utils"

export interface CommunePickerValue {
  commune_code: string
  ward: string | null
  province: string | null
  area_code: string | null
}

interface CommunePickerProps {
  id?: string
  value: CommunePickerValue | null
  onChange: (value: CommunePickerValue | null) => void
  disabled?: boolean
}

export function CommunePicker({
  id,
  value,
  onChange,
  disabled = false,
}: CommunePickerProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [debounced, setDebounced] = useState("")

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300)
    return () => clearTimeout(t)
  }, [query])

  const enabled = debounced.length >= 2
  const { data, isLoading } = useCommunes({
    q: enabled ? debounced : null,
    activeOnly: true,
    page: 1,
    pageSize: 30,
  })
  const items = enabled ? (data?.items ?? []) : []

  const label = value
    ? `${value.ward ?? "?"} (${value.commune_code})${value.province ? ` — ${value.province}` : ""}`
    : "Chọn xã/phường (gõ tên hoặc mã xã)…"

  return (
    <div className="flex items-stretch gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            id={id}
            type="button"
            variant="outline"
            role="combobox"
            aria-expanded={open}
            aria-label="Chọn xã/phường nơi trường đặt"
            className="flex-1 justify-between font-normal"
            disabled={disabled}
          >
            <span className={cn("truncate", !value && "text-muted-foreground")}>
              {label}
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="w-[var(--radix-popover-trigger-width)] p-0"
          align="start"
        >
          <Command shouldFilter={false}>
            <CommandInput
              placeholder="Gõ tên xã/phường hoặc mã xã…"
              value={query}
              onValueChange={setQuery}
            />
            <CommandList>
              {!enabled && <CommandEmpty>Gõ tối thiểu 2 ký tự</CommandEmpty>}
              {enabled && isLoading && (
                <div className="text-muted-foreground flex items-center justify-center py-4 text-sm">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Đang tìm…
                </div>
              )}
              {enabled && !isLoading && items.length === 0 && (
                <CommandEmpty>
                  Không có xã nào khớp trong bảng xã → KV (đang hiệu lực).
                </CommandEmpty>
              )}
              {items.length > 0 && (
                <CommandGroup>
                  {items.map((c) => (
                    <CommandItem
                      key={c.id}
                      value={`${c.id}`}
                      onSelect={() => {
                        onChange({
                          commune_code: c.commune_code,
                          ward: c.ward,
                          province: c.province,
                          area_code: c.area_code,
                        })
                        setOpen(false)
                      }}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-4 w-4",
                          value?.commune_code === c.commune_code
                            ? "opacity-100"
                            : "opacity-0",
                        )}
                      />
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate font-medium">{c.ward}</span>
                        <span className="text-muted-foreground truncate text-xs">
                          {c.commune_code} — {c.province}
                          <span className="text-info-700 ml-2 font-medium">
                            [{c.area_code}]
                          </span>
                        </span>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {value && !disabled && (
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => onChange(null)}
          aria-label="Bỏ chọn xã"
          className="text-muted-foreground hover:text-destructive shrink-0"
        >
          <X className="h-4 w-4" />
        </Button>
      )}
    </div>
  )
}
