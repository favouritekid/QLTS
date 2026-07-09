// src/hooks/useSmsContacts.ts
/**
 * React Query hooks cho SMS Marketing — Contact / Group / Consent (PR-6b).
 * Tiêu thụ router PR-2 (sms_contacts.py). Tất cả `require_admin` ở BE.
 */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"

import {
  addContactToGroup,
  appendConsentEvent,
  createSmsContact,
  createSmsContactGroup,
  getSmsContactGroup,
  getSmsContactInterests,
  listConsentEvents,
  listGroupContacts,
  listSmsContactGroups,
  listSmsContacts,
  removeContactFromGroup,
  updateSmsContact,
  updateSmsContactGroup,
  uploadContactsToGroup,
  type SmsContactGroupListParams,
  type SmsContactListParams,
  type UploadContactsPayload,
} from "@/lib/api/sms"
import { parseApiError } from "@/lib/utils/api-errors"
import type {
  SmsConsentEventCreateInput,
  SmsContactCreateInput,
  SmsContactGroupCreateInput,
  SmsContactGroupUpdateInput,
  SmsContactUpdateInput,
} from "@/lib/zod/sms"
import type { ApiErrorResponse } from "@/types/api.types"

type ApiError = AxiosError<ApiErrorResponse>

// ---------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------
export const smsContactKeys = {
  all: ["sms-contacts"] as const,
  groups: (p: SmsContactGroupListParams) =>
    [...smsContactKeys.all, "groups", p] as const,
  group: (id: number) => [...smsContactKeys.all, "group", id] as const,
  groupContacts: (id: number, p: SmsContactListParams) =>
    [...smsContactKeys.all, "group-contacts", id, p] as const,
  contacts: (p: SmsContactListParams) =>
    [...smsContactKeys.all, "contacts", p] as const,
  consentEvents: (contactId: number) =>
    [...smsContactKeys.all, "consent-events", contactId] as const,
  interests: (contactId: number) =>
    [...smsContactKeys.all, "interests", contactId] as const,
}

function invalidateContacts(qc: ReturnType<typeof useQueryClient>) {
  // Mọi danh sách contact + group (member_count, consent) có thể đổi.
  qc.invalidateQueries({ queryKey: smsContactKeys.all })
}

// ---------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------
export function useSmsContactGroups(
  params: SmsContactGroupListParams = {},
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: smsContactKeys.groups(params),
    queryFn: () => listSmsContactGroups(params),
    enabled: options.enabled ?? true,
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
  })
}

export function useSmsContactGroup(groupId: number | null) {
  return useQuery({
    queryKey: smsContactKeys.group(groupId ?? 0),
    queryFn: () => getSmsContactGroup(groupId as number),
    enabled: groupId != null,
    staleTime: 30 * 1000,
  })
}

export function useGroupContacts(
  groupId: number | null,
  params: SmsContactListParams = {},
) {
  return useQuery({
    queryKey: smsContactKeys.groupContacts(groupId ?? 0, params),
    queryFn: () => listGroupContacts(groupId as number, params),
    enabled: groupId != null,
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
  })
}

export function useSmsContacts(params: SmsContactListParams = {}) {
  return useQuery({
    queryKey: smsContactKeys.contacts(params),
    queryFn: () => listSmsContacts(params),
    placeholderData: keepPreviousData,
    staleTime: 30 * 1000,
  })
}

export function useConsentEvents(contactId: number | null) {
  return useQuery({
    queryKey: smsContactKeys.consentEvents(contactId ?? 0),
    queryFn: () => listConsentEvents(contactId as number, { limit: 100 }),
    enabled: contactId != null,
    staleTime: 30 * 1000,
  })
}

/** Hồ sơ "quan tâm ngành" của 1 contact. `enabled` để lazy-fetch khi mở chi
 * tiết. BE gác quyền (require_admin) → dùng kết quả API, không đoán theo role. */
export function useContactSmsInterests(
  contactId: number | null,
  enabled = true,
) {
  return useQuery({
    queryKey: smsContactKeys.interests(contactId ?? 0),
    queryFn: () => getSmsContactInterests(contactId as number),
    enabled: enabled && contactId != null && contactId > 0,
    staleTime: 60 * 1000,
    retry: false,
  })
}

// ---------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------
export function useCreateContactGroup() {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, SmsContactGroupCreateInput>({
    mutationFn: createSmsContactGroup,
    onSuccess: () => {
      toast.success("Đã tạo nhóm liên hệ.")
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể tạo nhóm.")),
  })
}

export function useUpdateContactGroup() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { id: number; data: SmsContactGroupUpdateInput }
  >({
    mutationFn: ({ id, data }) => updateSmsContactGroup(id, data),
    onSuccess: () => {
      toast.success("Đã cập nhật nhóm.")
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể cập nhật nhóm.")),
  })
}

export function useUploadContacts() {
  const qc = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof uploadContactsToGroup>>,
    ApiError,
    { groupId: number; payload: UploadContactsPayload }
  >({
    mutationFn: ({ groupId, payload }) =>
      uploadContactsToGroup(groupId, payload),
    onSuccess: () => {
      // Toast chi tiết do component hiển thị (counts); chỉ invalidate ở đây.
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Import thất bại.")),
  })
}

export function useCreateContact() {
  const qc = useQueryClient()
  return useMutation<unknown, ApiError, SmsContactCreateInput>({
    mutationFn: createSmsContact,
    onSuccess: () => {
      toast.success("Đã tạo liên hệ.")
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể tạo liên hệ.")),
  })
}

export function useUpdateContact() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { id: number; data: SmsContactUpdateInput }
  >({
    mutationFn: ({ id, data }) => updateSmsContact(id, data),
    onSuccess: () => {
      toast.success("Đã cập nhật liên hệ.")
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể cập nhật liên hệ.")),
  })
}

export function useAppendConsentEvent() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { contactId: number; data: SmsConsentEventCreateInput }
  >({
    mutationFn: ({ contactId, data }) => appendConsentEvent(contactId, data),
    onSuccess: () => {
      toast.success("Đã ghi sự kiện consent.")
      invalidateContacts(qc)
    },
    onError: (e) =>
      toast.error(parseApiError(e, "Không thể ghi sự kiện consent.")),
  })
}

export function useAddContactToGroup() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { contactId: number; group_id: number; note?: string }
  >({
    mutationFn: ({ contactId, group_id, note }) =>
      addContactToGroup(contactId, { group_id, note }),
    onSuccess: () => {
      toast.success("Đã thêm vào nhóm.")
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể thêm vào nhóm.")),
  })
}

export function useRemoveContactFromGroup() {
  const qc = useQueryClient()
  return useMutation<
    unknown,
    ApiError,
    { contactId: number; groupId: number }
  >({
    mutationFn: ({ contactId, groupId }) =>
      removeContactFromGroup(contactId, groupId),
    onSuccess: () => {
      toast.success("Đã gỡ khỏi nhóm.")
      invalidateContacts(qc)
    },
    onError: (e) => toast.error(parseApiError(e, "Không thể gỡ khỏi nhóm.")),
  })
}
