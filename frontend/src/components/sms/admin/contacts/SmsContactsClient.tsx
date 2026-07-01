// src/components/sms/admin/contacts/SmsContactsClient.tsx
"use client"

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs"

import { SmsContactsPanel } from "./SmsContactsPanel"
import { SmsGroupsPanel } from "./SmsGroupsPanel"

/**
 * Quản lý liên hệ SMS (admin). 2 tab:
 * - "Nhóm": CRUD nhóm + import CSV/XLSX kèm bằng chứng consent.
 * - "Liên hệ": danh sách toàn cục + tạo/sửa + ledger consent + gán nhóm.
 */
export function SmsContactsClient() {
  return (
    <Tabs defaultValue="groups" className="space-y-4">
      <TabsList>
        <TabsTrigger value="groups">Nhóm liên hệ</TabsTrigger>
        <TabsTrigger value="contacts">Liên hệ</TabsTrigger>
      </TabsList>
      <TabsContent value="groups">
        <SmsGroupsPanel />
      </TabsContent>
      <TabsContent value="contacts">
        <SmsContactsPanel />
      </TabsContent>
    </Tabs>
  )
}
