/**
 * CHỈ cho test GĐ2-B (màn lần xét): dữ liệu GIẢ theo đúng hình máy chủ (`app/schemas/admission_review.py`, HĐ4 bản 4 §3, §9).
 * Không dữ liệu cá nhân (họ tên = `<họ tên>`). Mỗi hàm trả một đối tượng đủ trường; test ghi đè đúng trường cần.
 */
export const API = "http://localhost:8000"
/** Tiền tố E1–E9. */
export const RS = `${API}/api/admission-config/review-sessions`

type Obj = Record<string, unknown>

export function floorGia(over: Obj = {}): Obj {
  return {
    offering_academic_info_id: 41,
    floor_score: "15.00",
    major_code: "<mã>",
    major_name: "<tên ngành>",
    offering_type: "<loại hình>",
    annual_admission_quota: 30,
    group_code: "N1",
    is_deleted: false,
    updated_by_user_id: 1,
    updated_at: "2026-11-24T02:05:00Z",
    ...over,
  }
}

export function runSummaryGia(over: Obj = {}): Obj {
  return {
    id: 11,
    kind: "evaluate",
    status: "done",
    rule_version: "gd2b-1",
    requested_by_user_id: 1,
    requested_at: "2026-11-24T02:12:00Z",
    finished_at: "2026-11-24T02:12:14Z",
    duration_ms: 14000,
    tab_counts: { auto: 120, needs_decision: 8, not_passed: 31, ineligible: 57 },
    config_changed_since_run: false,
    ...over,
  }
}

/** `SessionOut` — lần xét nháp số 3 năm 2026, đủ ba hành động. */
export function sessionGia(over: Obj = {}): Obj {
  return {
    id: 3,
    academic_year: 2026,
    admission_round: { id: 7, round_code: "D2", round_name: "Đợt 2" },
    seq_no: 3,
    status: "draft",
    version: 2,
    created_by_user_id: 1,
    created_at: "2026-11-22T01:00:00Z",
    updated_at: "2026-11-24T02:05:00Z",
    cancelled_by_user_id: null,
    cancelled_at: null,
    cancel_reason: null,
    quota_table: { status: "locked", version: 2, quota_fingerprint: "a".repeat(64) },
    floors: [floorGia()],
    latest_run: runSummaryGia(),
    latest_done_run_id: 11,
    available_actions: ["edit_floors", "run_evaluate", "cancel"],
    ...over,
  }
}

/** HĐ4 §9 — phản hồi E5 (bản rút gọn của hợp đồng, điền đủ trường còn lại). */
export function sessionDaHuyGia(over: Obj = {}): Obj {
  return sessionGia({
    status: "cancelled",
    version: 3,
    floors: [],
    available_actions: [],
    cancelled_by_user_id: 1,
    cancelled_at: "2026-11-24T03:00:00Z",
    cancel_reason: "<lý do>",
    latest_done_run_id: 11,
    ...over,
  })
}

/** `SessionListItemOut`. */
export function listItemGia(over: Obj = {}): Obj {
  return {
    id: 3,
    academic_year: 2026,
    admission_round: { id: 7, round_code: "D2", round_name: "Đợt 2" },
    seq_no: 3,
    status: "draft",
    version: 2,
    created_by_user_id: 1,
    created_at: "2026-11-22T01:00:00Z",
    floor_count: 14,
    latest_run: runSummaryGia(),
    ...over,
  }
}

/** Trang (HĐ4 §1.6). */
export function pageGia(items: Obj[], over: Obj = {}): Obj {
  return { items, total: items.length, page: 1, page_size: 20, total_pages: items.length ? 1 : 0, ...over }
}

/** `RunOut` — lượt 11 đã xong. */
export function runGia(over: Obj = {}): Obj {
  return {
    id: 11,
    session_id: 3,
    kind: "evaluate",
    status: "done",
    rule_version: "gd2b-1",
    requested_by_user_id: 1,
    requested_at: "2026-11-24T02:12:00Z",
    started_at: "2026-11-24T02:12:00Z",
    finished_at: "2026-11-24T02:12:14Z",
    duration_ms: 14000,
    error_code: null,
    inputs: {
      academic_year: 2026,
      session_version: 2,
      floors: [{ offering_academic_info_id: 41, floor_score: "15.00" }],
      quota_table: { status: "locked", version: 2, quota_fingerprint: "a".repeat(64) },
      fee_gate_mode: "legacy",
      snapshot_at: "2026-11-24T02:12:00Z",
    },
    summary: {
      rows_total: 216,
      pool_total: 216,
      tab_counts: { auto: 120, needs_decision: 8, not_passed: 31, ineligible: 57 },
      reason_counts: { tie_at_last_seat: 3 },
      flag_counts: {},
      warnings: [],
    },
    quota_view: {
      majors: [
        {
          offering_academic_info_id: 41,
          offering_id: 12,
          major_code: "<mã>",
          major_name: "<tên ngành>",
          offering_type: "<loại hình>",
          group_id: 5,
          group_code: "N1",
          annual_admission_quota: 30,
          floor_score: "15.00",
          used_publish: 0,
          used_approved: 0,
          used: 0,
          remaining: 30,
          state: "ok",
          candidates: 40,
          auto: 30,
          needs_decision: 2,
          offering_inactive: false,
          major_inactive: false,
        },
      ],
      groups: [
        {
          group_id: 5,
          code: "N1",
          name: "<nhóm>",
          ceiling: 100,
          used_publish: 0,
          used_approved: 0,
          used: 0,
          auto_in_run: 30,
          remaining_after_auto: -2,
          would_exceed: true,
        },
      ],
    },
    config_changed_since_run: false,
    ...over,
  }
}

/** HĐ4 §9 — E9 dòng `ineligible` vì mất cấu hình giấy. */
export const E9_MAT_CAU_HINH_GIAY: Obj = {
  profile_id: 1003,
  full_name: "<họ tên>",
  unit_id: 4,
  profile_status: "submitted",
  tab: "ineligible",
  reason_codes: ["document_config_missing"],
  flags: [],
  decision_hints: [],
  document_gaps: null,
  considered_choice: null,
  review_total: null,
  score_parts: null,
  floor_score: null,
  rank_in_major: null,
  within_seats: null,
  ethnic_priority_state: null,
  per_choice: [],
  prior_year_findings: [],
  row_hash: "b".repeat(64),
}

/** HĐ4 §9 — E9 dòng `ineligible` vì giấy bắt buộc chưa có dòng + một giấy chưa duyệt. */
export const E9_THIEU_GIAY: Obj = {
  ...E9_MAT_CAU_HINH_GIAY,
  profile_id: 1004,
  profile_status: "resubmitted",
  reason_codes: ["mandatory_document_missing", "mandatory_document_not_verified"],
  document_gaps: { missing: ["hoc_ba_thpt"], not_verified: ["giay_khai_sinh"] },
}

/** HĐ4 §9 — E9 dòng `needs_decision` (bằng điểm ở chỗ cuối). */
export const E9_BANG_DIEM_CHO_CUOI: Obj = {
  profile_id: 1001,
  full_name: "<họ tên>",
  unit_id: 4,
  profile_status: "submitted",
  tab: "needs_decision",
  reason_codes: ["tie_at_last_seat"],
  flags: [],
  document_gaps: null,
  decision_hints: ["admit_over_major_quota", "consider_next_choice"],
  considered_choice: {
    choice_id: 5001,
    display_order: 1,
    offering_academic_info_id: 41,
    offering_id: 12,
    admission_path_id: 88,
    major_code: "<mã>",
    major_name: "<tên ngành>",
    offering_type: "<loại hình>",
  },
  review_total: "18.50",
  score_parts: { subject_total: "17.00", area: "0.50", object: "1.00", priority_total: "1.50" },
  floor_score: "15.00",
  rank_in_major: 40,
  within_seats: false,
  ethnic_priority_state: "full_evidence",
  per_choice: [
    {
      choice_id: 5001,
      display_order: 1,
      offering_academic_info_id: 41,
      status: "passed_floor",
      reason_codes: [],
      review_total: "18.50",
      floor_score: "15.00",
    },
    {
      choice_id: 5002,
      display_order: 2,
      offering_academic_info_id: 57,
      status: "not_considered",
      reason_codes: [],
      review_total: null,
      floor_score: null,
    },
  ],
  prior_year_findings: [],
  row_hash: "c".repeat(64),
}

/** HĐ4 §9 — thân 400 của E4 khi học vụ vừa bị dời năm. */
export const E4_BAD_MEMBER_BODY: Obj = {
  reason_code: "review_floor_bad_member",
  offering_academic_info_ids: [41],
  detail: "Có học vụ không thuộc năm 2026 (không tồn tại, đã xoá, hoặc khác năm).",
  error_code: "VALIDATION_ERROR",
}

/** Đợt của một năm — hình `AdmissionRoundResponse` (route có sẵn). */
export function roundGia(over: Obj = {}): Obj {
  return {
    id: 7,
    academic_year: 2026,
    round_code: "D2",
    round_name: "Đợt 2",
    start_date: null,
    end_date: null,
    is_active: true,
    archived_at: null,
    extended_at: null,
    extended_by_user_id: null,
    extension_reason: null,
    allow_multi_nv: false,
    confirm_expiry_hours: 168,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  }
}
