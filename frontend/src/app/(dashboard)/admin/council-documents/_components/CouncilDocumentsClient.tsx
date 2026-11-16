"use client"

import Link from "next/link"
import { useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { canBuildFromList, useCouncilDocumentPermissions } from "@/hooks/admin/useCouncilDocuments"
import type { CouncilDocumentPermissionKey } from "@/lib/zod/council-documents"

import { CouncilErrorAlert } from "./CouncilErrorAlert"
import { CouncilDeletionLogPanel, CouncilDownloadLogPanel } from "./CouncilLogPanels"
import { CouncilSetList } from "./CouncilSetList"
import { CouncilTemplatePanel } from "./CouncilTemplatePanel"
import { CreateCouncilSetForm } from "./CreateCouncilSetForm"

type Tab = "bo" | "tao" | "mau" | "nhat-ky-tai" | "nhat-ky-xoa"

/** Thẻ ↔ cờ của máy chủ: thẻ chỉ hiện khi cờ bật (không xét vai). */
const TABS: { tabId: Tab; label: string; permission: CouncilDocumentPermissionKey }[] = [
  { tabId: "bo", label: "Bộ văn bản", permission: "xem_danh_sach_bo" },
  { tabId: "tao", label: "Tạo bộ", permission: "tao_bo" },
  { tabId: "mau", label: "Kho mẫu", permission: "xem_mau" },
  { tabId: "nhat-ky-tai", label: "Nhật ký tải", permission: "xem_nhat_ky_tai" },
  { tabId: "nhat-ky-xoa", label: "Nhật ký xoá", permission: "xem_nhat_ky_xoa" },
]

export function CouncilDocumentsClient() {
  const vm = useCouncilDocumentPermissions()
  const [tab, setTab] = useState<Tab | null>(null)

  if (vm.state === "loading") {
    return (
      <div className="flex items-center gap-2 text-muted-foreground" data-testid="council-loading">
        <Loader2 className="h-4 w-4 animate-spin" /> Đang tải quyền…
      </div>
    )
  }
  if (vm.state === "forbidden") {
    return (
      <p className="text-muted-foreground" data-testid="council-forbidden">
        Bạn không có quyền xem văn bản Hội đồng tuyển sinh.
      </p>
    )
  }
  if (vm.state === "error") return <CouncilErrorAlert error={vm.error} testId="council-permission-error" />

  const q = vm.permissions
  const visibleTabs = TABS.filter((t) => q[t.permission])
  if (visibleTabs.length === 0) {
    return (
      <p className="text-muted-foreground" data-testid="council-forbidden">
        Bạn không có quyền xem văn bản Hội đồng tuyển sinh.
      </p>
    )
  }
  const selecting = tab !== null && visibleTabs.some((t) => t.tabId === tab) ? tab : visibleTabs[0].tabId

  return (
    <Tabs value={selecting} onValueChange={(v) => setTab(v as Tab)}>
      <TabsList>
        {visibleTabs.map((t) => (
          <TabsTrigger key={t.tabId} value={t.tabId} data-testid={`tab-${t.tabId}`}>
            {t.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {q.xem_danh_sach_bo ? (
        <TabsContent value="bo" className="pt-4">
          <CouncilSetList canOpenDetail={q.xem_chi_tiet_bo} canZip={q.tai_ca_bo} canFilterCreator={q.xem_nguoi_tao_bo} />
        </TabsContent>
      ) : null}
      {q.tao_bo ? (
        <TabsContent value="tao" className="space-y-6 pt-4">
          {canBuildFromList(q) ? (
            <div className="space-y-2 rounded border p-4" data-testid="dung-tu-danh-sach">
              <h2 className="text-lg font-semibold">Dựng từ danh sách hồ sơ</h2>
              <p className="text-sm text-muted-foreground">
                Chọn hồ sơ từ danh sách (lọc, tìm, tick), kiểm tra & chốt, nhập tham số rồi dựng bộ. Không cần dán từng mã CCCD.
              </p>
              <Button asChild data-testid="dung-tu-danh-sach-nut">
                <Link href="/admin/council-documents/moi">Dựng văn bản Hội đồng →</Link>
              </Button>
            </div>
          ) : null}
          <div className="space-y-2">
            {canBuildFromList(q) ? <h2 className="text-lg font-semibold">Hoặc: dán danh sách mã hồ sơ (cách cũ)</h2> : null}
            <CreateCouncilSetForm canOpenDetail={q.xem_chi_tiet_bo} />
          </div>
        </TabsContent>
      ) : null}
      {q.xem_mau ? (
        <TabsContent value="mau" className="pt-4">
          <CouncilTemplatePanel canUpload={q.tai_mau_len} />
        </TabsContent>
      ) : null}
      {q.xem_nhat_ky_tai ? (
        <TabsContent value="nhat-ky-tai" className="pt-4">
          <CouncilDownloadLogPanel />
        </TabsContent>
      ) : null}
      {q.xem_nhat_ky_xoa ? (
        <TabsContent value="nhat-ky-xoa" className="pt-4">
          <CouncilDeletionLogPanel />
        </TabsContent>
      ) : null}
    </Tabs>
  )
}
