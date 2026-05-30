export type PublicAdmissionsMoney = number | string | null

export interface PublicSemesterTuitionItem {
  semester_no: number
  amount: PublicAdmissionsMoney
}

export interface PublicAdmissionsMethodTag {
  id: number
  code: string
  name: string
}

export interface PublicAdmissionsAcademicInfoSummary {
  id: number
  academic_year: number
  tuition_fee_per_year: PublicAdmissionsMoney
  annual_admission_quota: number | null
  cutoff_score_previous_year: PublicAdmissionsMoney
  target_audience: string | null
  applied_discount_policy_ids: number[]
  semester_tuitions?: PublicSemesterTuitionItem[]
  semester_1_tuition?: PublicAdmissionsMoney
}

export interface PublicAdmissionsOfferingSummary {
  id: number
  offering_type: string
  duration_semesters: number | null
  total_credits: number | null
  academic_info: PublicAdmissionsAcademicInfoSummary
  admission_methods: PublicAdmissionsMethodTag[]
}

export interface PublicAdmissionsProgramSummary {
  id: number
  code: string
  name: string
  degree_level: string
  is_heavy: boolean
  offering_count: number
  academic_years: number[]
  tuition_min: PublicAdmissionsMoney
  tuition_max: PublicAdmissionsMoney
  semester_1_tuition_min?: PublicAdmissionsMoney
  semester_1_tuition_max?: PublicAdmissionsMoney
  offerings: PublicAdmissionsOfferingSummary[]
}

export interface PublicAdmissionsDegreeLevelGroup {
  degree_level: string
  program_count: number
  offering_count: number
  offering_types: string[]
  academic_years: number[]
  tuition_min: PublicAdmissionsMoney
  tuition_max: PublicAdmissionsMoney
  semester_1_tuition_min?: PublicAdmissionsMoney
  semester_1_tuition_max?: PublicAdmissionsMoney
  programs: PublicAdmissionsProgramSummary[]
}

export interface PublicAdmissionsProgramsMeta {
  degree_level_count: number
  program_count: number
  offering_count: number
  latest_academic_year: number | null
  offering_types: string[]
}

export interface PublicAdmissionsProgramsResponse {
  summary: PublicAdmissionsProgramsMeta
  degree_levels: PublicAdmissionsDegreeLevelGroup[]
}

export interface PublicAdmissionsMethodUsage {
  id: number
  code: string
  name: string
  description: string | null
  requires_gpa: boolean
  requires_subject_scores: boolean
  public_program_count: number
  public_offering_count: number
  public_path_count: number
  academic_years: number[]
}

export interface PublicAdmissionsSubjectGroupUsage {
  id: number
  code: string
  name: string
  subjects: string[]
  method_codes: string[]
  public_path_count: number
}

export interface PublicAdmissionsMethodsMeta {
  method_count: number
  subject_group_count: number
  public_path_count: number
}

export interface PublicAdmissionsMethodsResponse {
  summary: PublicAdmissionsMethodsMeta
  methods: PublicAdmissionsMethodUsage[]
  subject_groups: PublicAdmissionsSubjectGroupUsage[]
}

export interface PublicAdmissionsDocumentRequirement {
  document_type_id: number
  document_type_code: string
  document_type_name: string
  document_type_description: string | null
  is_mandatory: boolean
  requires_upload: boolean
  submission_format: string | null
  display_order: number
  source: string
}

export interface PublicAdmissionsMethodDocumentChecklist {
  method_id: number
  method_code: string
  method_name: string
  source: string
  public_program_count: number
  public_offering_count: number
  public_path_count: number
  documents: PublicAdmissionsDocumentRequirement[]
}

// §9 (feat/document-group-audience-merge): lớp giấy tờ theo đối tượng/trình độ.
export interface PublicAdmissionsAudienceDocumentLayer {
  audience: string
  audience_label: string
  documents: PublicAdmissionsDocumentRequirement[]
}

export interface PublicAdmissionsOfferingTypeDocumentChecklist {
  offering_type_id: number
  offering_type_code: string
  offering_type_name: string
  public_program_count: number
  public_offering_count: number
  public_method_count: number
  sample_programs: string[]
  shared_documents: PublicAdmissionsDocumentRequirement[]
  // §9: NỀN = shared_documents; audience_layers = lớp theo đối tượng.
  audience_layers: PublicAdmissionsAudienceDocumentLayer[]
  method_documents: PublicAdmissionsMethodDocumentChecklist[]
}

export interface PublicAdmissionsDocumentsMeta {
  offering_type_count: number
  method_count: number
  document_type_count: number
  public_path_count: number
}

export interface PublicAdmissionsDocumentsResponse {
  summary: PublicAdmissionsDocumentsMeta
  offering_types: PublicAdmissionsOfferingTypeDocumentChecklist[]
}

export interface PublicAdmissionsDiscountPolicySummary {
  id: number
  code: string
  name: string
  description: string | null
  discount_type: string
  discount_value: PublicAdmissionsMoney
  valid_from: string | null
  valid_to: string | null
  is_stackable: boolean
  priority: number
}

export interface PublicAdmissionsTuitionOffering {
  program_id: number
  program_name: string
  program_code: string
  degree_level: string
  offering_id: number
  offering_type: string
  academic_info_id: number
  academic_year: number
  tuition_fee_per_year: PublicAdmissionsMoney
  annual_admission_quota: number | null
  applied_discount_policy_ids: number[]
  semester_tuitions?: PublicSemesterTuitionItem[]
  semester_1_tuition?: PublicAdmissionsMoney
}

export interface PublicAdmissionsTuitionBand {
  degree_level: string
  published_offering_count: number
  academic_years: number[]
  tuition_min: PublicAdmissionsMoney
  tuition_max: PublicAdmissionsMoney
  semester_1_tuition_min?: PublicAdmissionsMoney
  semester_1_tuition_max?: PublicAdmissionsMoney
}

export interface PublicAdmissionsTuitionMeta {
  program_count: number
  offering_count: number
  policy_count: number
  latest_academic_year: number | null
}

export interface PublicAdmissionsTuitionResponse {
  summary: PublicAdmissionsTuitionMeta
  degree_levels: PublicAdmissionsTuitionBand[]
  offerings: PublicAdmissionsTuitionOffering[]
  discount_policies: PublicAdmissionsDiscountPolicySummary[]
}
