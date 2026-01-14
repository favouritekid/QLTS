/**
 * Program Data API Client
 *
 * API functions for Phase 2 program entities:
 * - Major Programs
 * - Program Offerings
 * - Offering Academic Info
 */

import { api } from "./client";
import type {
  OfferingAcademicInfo,
} from "@/app/(dashboard)/admin/admission-config/_components/shared/types";

// ============================================
// TYPES FOR API
// ============================================

interface MajorProgramCreate {
  code: string;
  name: string;
  degree_level: string;
  unit_id: number;
  is_heavy: boolean;
  is_active?: boolean;
}

interface MajorProgramUpdate {
  name?: string;
  degree_level?: string;
  unit_id?: number;
  is_heavy?: boolean;
  is_active?: boolean;
}

interface ProgramOfferingCreate {
  program_id: number;
  offering_type: string; // Backend expects string name
  duration_semesters?: number;
  total_credits?: number;
  scoring_rules?: any; // Nested JSON
  is_active?: boolean;
}

interface ProgramOfferingUpdate {
  offering_type?: string; 
  duration_semesters?: number;
  total_credits?: number;
  scoring_rules?: any; // Nested JSON
  is_active?: boolean;
}

interface AcademicInfoCreate {
  offering_id: number;
  academic_year: number;
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
}

interface AcademicInfoUpdate {
  tuition_fee_per_year?: number;
  annual_admission_quota?: number;
  is_published?: boolean;
}

// ============================================
// MAJOR PROGRAMS
// ============================================

export async function getMajorPrograms() {
  const response = await api.get("/api/programs");
  return response.data;
}

export async function createMajorProgram(data: MajorProgramCreate) {
  const response = await api.post("/api/admin/programs", data);
  return response.data;
}

export async function updateMajorProgram(id: number, data: MajorProgramUpdate) {
  const response = await api.put(`/api/admin/programs/${id}`, data);
  return response.data;
}

export async function deleteMajorProgram(id: number) {
  await api.delete(`/api/admin/programs/${id}`);
}

// ============================================
// PROGRAM OFFERINGS
// ============================================

export async function getProgramOfferings() {
  const response = await api.get("/api/program-offerings");
  return response.data;
}

export async function getProgramOfferingsByMajor(majorId: number) {
  const response = await api.get(`/api/programs/${majorId}/offerings`);
  return response.data;
}

export async function createProgramOffering(data: ProgramOfferingCreate) {
  const response = await api.post(`/api/admin/programs/${data.program_id}/offerings`, data);
  return response.data;
}

export async function updateProgramOffering(id: number, data: ProgramOfferingUpdate) {
  const response = await api.put(`/api/admin/offerings/${id}`, data);
  return response.data;
}

export async function deleteProgramOffering(id: number) {
  await api.delete(`/api/admin/offerings/${id}`);
}

// ============================================
// OFFERING ACADEMIC INFO
// ============================================

export async function getOfferingAcademicInfos() {
  const response = await api.get("/api/offerings/academic-info");
  return response.data;
}

export async function getAcademicInfoByOffering(offeringId: number) {
  const response = await api.get(`/api/offerings/${offeringId}/academic-info`);
  return response.data;
}

export async function createOfferingAcademicInfo(data: AcademicInfoCreate) {
  const response = await api.post(`/api/offerings/${data.offering_id}/academic-info`, data);
  return response.data;
}

export async function updateOfferingAcademicInfo(id: number, data: AcademicInfoUpdate) {
  const response = await api.patch(`/api/academic-info/${id}`, data);
  return response.data;
}

export async function deleteOfferingAcademicInfo(id: number) {
  await api.delete(`/api/academic-info/${id}`);
}

// ============================================
// HELPER FUNCTIONS
// ============================================

export async function checkAcademicInfoExists(offeringId: number, year: number): Promise<boolean> {
  try {
    const infos = await getAcademicInfoByOffering(offeringId);
    return infos.some((info: OfferingAcademicInfo) => info.academic_year === year);
  } catch {
    return false;
  }
}
