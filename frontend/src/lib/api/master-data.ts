/**
 * Master Data API Client
 *
 * API functions for Phase 1 master data entities:
 * - Organization Units
 * - Offering Types
 * - Admission Methods
 * - Document Types
 * - Subjects
 * - Subject Groups
 */

import { api } from "./client";
import type {
  BaseEntityCreate,
  BaseEntityUpdate,
  SharedDocumentGroupUpdate,
} from "@/app/(dashboard)/admin/admission-config/_components/shared/types";

// ============================================
// EXTENDED TYPES FOR API
// ============================================

interface AdmissionMethodCreate extends BaseEntityCreate {
  requires_gpa?: boolean;
  requires_subject_scores?: boolean;
}

interface AdmissionMethodUpdate extends BaseEntityUpdate {
  requires_gpa?: boolean;
  requires_subject_scores?: boolean;
}

interface SubjectCreate {
  code: string;
  name_vi: string;
  name_en?: string;
  display_order?: number;
  is_active?: boolean;
}

interface SubjectUpdate {
  name_vi?: string;
  name_en?: string;
  display_order?: number;
  is_active?: boolean;
}

type SubjectGroupCreate = BaseEntityCreate;

type SubjectGroupUpdate = BaseEntityUpdate;

// ============================================
// ORGANIZATION UNITS
// ============================================

export async function getOrganizationUnits() {
  const response = await api.get("/api/organization-units");
  return response.data;
}

export async function createOrganizationUnit(data: BaseEntityCreate) {
  const response = await api.post("/api/admin/organization-units", data);
  return response.data;
}

export async function updateOrganizationUnit(id: number, data: BaseEntityUpdate) {
  const response = await api.put(`/api/admin/organization-units/${id}`, data);
  return response.data;
}

export async function deleteOrganizationUnit(id: number) {
  await api.delete(`/api/admin/organization-units/${id}`);
}

// ============================================
// OFFERING TYPES
// ============================================

export async function getOfferingTypes() {
  const response = await api.get("/api/admin/offering-types?active_only=false");
  return response.data;
}

export async function createOfferingType(data: BaseEntityCreate) {
  const response = await api.post("/api/admin/offering-types", data);
  return response.data;
}

export async function updateOfferingType(id: number, data: BaseEntityUpdate) {
  const response = await api.put(`/api/admin/offering-types/${id}`, data);
  return response.data;
}

export async function deleteOfferingType(id: number) {
  await api.delete(`/api/admin/offering-types/${id}`);
}

// ============================================
// ADMISSION METHODS
// ============================================

export async function getAdmissionMethods() {
  const response = await api.get("/api/admission-config/methods");
  return response.data.methods || response.data;
}

export async function createAdmissionMethod(data: AdmissionMethodCreate) {
  const response = await api.post("/api/admission-config/methods", data);
  return response.data;
}

export async function updateAdmissionMethod(id: number, data: AdmissionMethodUpdate) {
  const response = await api.put(`/api/admission-config/methods/${id}`, data);
  return response.data;
}

export async function deleteAdmissionMethod(id: number) {
  await api.delete(`/api/admission-config/methods/${id}`);
}

// ============================================
// DOCUMENT TYPES
// ============================================

export async function getDocumentTypes() {
  const response = await api.get("/api/admin/document-types?active_only=false");
  return response.data;
}

export async function createDocumentType(data: BaseEntityCreate) {
  const response = await api.post("/api/admin/document-types", data);
  return response.data;
}

export async function updateDocumentType(id: number, data: BaseEntityUpdate) {
  const response = await api.put(`/api/admin/document-types/${id}`, data);
  return response.data;
}

export async function deleteDocumentType(id: number) {
  await api.delete(`/api/admin/document-types/${id}`);
}

// ============================================
// SUBJECTS
// ============================================

export async function getSubjects() {
  const response = await api.get("/api/admission-config/subjects");
  return response.data.subjects || response.data;
}

export async function createSubject(data: SubjectCreate) {
  const response = await api.post("/api/admission-config/subjects", data);
  return response.data;
}

export async function updateSubject(id: number, data: SubjectUpdate) {
  const response = await api.put(`/api/admission-config/subjects/${id}`, data);
  return response.data;
}

export async function deleteSubject(id: number) {
  await api.delete(`/api/admission-config/subjects/${id}`);
}

// ============================================
// SUBJECT GROUPS
// ============================================

export async function getSubjectGroups() {
  const response = await api.get("/api/admission-config/subject-groups");
  return response.data.groups || response.data;
}

export async function createSubjectGroup(data: SubjectGroupCreate) {
  const response = await api.post("/api/admission-config/subject-groups", data);
  return response.data;
}

export async function updateSubjectGroup(id: number, data: SubjectGroupUpdate) {
  const response = await api.put(`/api/admission-config/subject-groups/${id}`, data);
  return response.data;
}

export async function deleteSubjectGroup(id: number) {
  await api.delete(`/api/admission-config/subject-groups/${id}`);
}

// ============================================
// SUBJECT GROUP M2M OPERATIONS
// ============================================

export async function addSubjectToGroup(groupId: number, subjectId: number, position: number) {
  const response = await api.post(`/api/admission-config/subject-groups/${groupId}/subjects`, {
    subject_id: subjectId,
    position,
  });
  return response.data;
}

export async function removeSubjectFromGroup(groupId: number, subjectId: number) {
  await api.delete(`/api/admission-config/subject-groups/${groupId}/subjects/${subjectId}`);
}

export async function updateSubjectPosition(groupId: number, subjectId: number, position: number) {
  const response = await api.put(
    `/api/admission-config/subject-groups/${groupId}/subjects/${subjectId}`,
    { position }
  );
  return response.data;
}

// ============================================
// SHARED DOCUMENT GROUPS
// ============================================

export async function getSharedDocumentGroup(offeringTypeId: number) {
  const response = await api.get(`/api/admission-config/document-groups/shared/${offeringTypeId}`);
  return response.data;
}

export async function upsertSharedDocumentGroup(offeringTypeId: number, data: SharedDocumentGroupUpdate) {
  const response = await api.put(`/api/admission-config/document-groups/shared/${offeringTypeId}`, data);
  return response.data;
}
