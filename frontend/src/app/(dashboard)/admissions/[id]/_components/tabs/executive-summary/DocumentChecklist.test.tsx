/**
 * DocumentChecklist permission gating (PR #5 review follow-up).
 *
 * The Step 7 checklist used to surface "Xác nhận kiểm tra" and per-row
 * reject buttons based purely on doc.status. With backend-computed
 * `can_verify` / `can_reject` flags now authoritative, officers (who
 * can't verify per Casbin + service guard) must not see those buttons
 * even when a doc is uploaded/paper-submitted.
 */
import { afterEach, describe, it, expect } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import { waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";

import { DocumentChecklist } from "./DocumentChecklist";

// GĐ1b: không còn mock hook giấy cũ — "Xác nhận kiểm tra" là lô MỘT hồ sơ, Từ chối qua hộp GĐ1b (axios THẬT + MSW).
afterEach(() => server.resetHandlers());

type DocRow = {
  code: string;
  label: string;
  status: string;
  is_mandatory: boolean;
  requires_upload: boolean;
  can_verify?: boolean;
  can_reject?: boolean;
  document_row_id?: number | null;
  row_version?: number | null;
  verified_format?: string | null;
  actual_submission_format?: string | null;
  submission_format?: string | null;
  file_path?: string | null;
};

function buildProfile(docs: DocRow[]) {
  return {
    id: 42,
    status: "submitted",
    // GĐ1b bản 5 B1: khoá định danh + cờ LUÔN có ⇒ mặc định "có dòng, mọi cờ tắt"; ca kiểm đè khi cần.
    documents_checklist: docs.map((d, i) => ({
      document_row_id: i + 1,
      row_version: 1,
      can_verify: false,
      can_reject: false,
      can_reset: false,
      can_view_history: false,
      verify_block_reason: null,
      requires_ack: false,
      reset_requires_reason: false,
      reset_keeps_evidence: false,
      ...d,
    })),
    applied_rules: {},
  };
}

async function openAndRender(profile: ReturnType<typeof buildProfile>) {
  // userEvent wraps interactions in act() so React state updates flush
  // before the next assertion — eliminates the act(...) warnings the
  // bare HTMLElement.click() emitted on the Collapsible trigger.
  const user = userEvent.setup();
  const utils = render(<DocumentChecklist profile={profile as never} />);
  const trigger = await screen.findByRole("button", {
    name: /checklist tài liệu bắt buộc/i,
  });
  await user.click(trigger);
  return utils;
}

describe("DocumentChecklist — PR #5 permission gating", () => {
  it("hides batch 'Xác nhận kiểm tra' when no doc has can_verify=true", async () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_verify: false,
        can_reject: false,
      },
      {
        code: "CCCD",
        label: "Căn cước",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
        can_verify: false,
        can_reject: false,
      },
    ]);
    await openAndRender(profile);
    expect(
      screen.queryByRole("button", { name: /xác nhận kiểm tra/i })
    ).not.toBeInTheDocument();
  });

  it("shows batch 'Xác nhận kiểm tra' when at least one doc grants can_verify=true", async () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_verify: true,
        can_reject: true,
      },
    ]);
    await openAndRender(profile);
    expect(
      await screen.findByRole("button", { name: /xác nhận kiểm tra/i })
    ).toBeInTheDocument();
  });

  it("hides per-row Reject button when can_reject=false", async () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_verify: false,
        can_reject: false,
      },
    ]);
    await openAndRender(profile);
    expect(
      screen.queryByRole("button", { name: /từ chối giấy/i })
    ).not.toBeInTheDocument();
  });

  it("shows per-row Reject button when can_reject=true", async () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_verify: true,
        can_reject: true,
      },
    ]);
    await openAndRender(profile);
    expect(
      await screen.findByRole("button", { name: /từ chối giấy/i })
    ).toBeInTheDocument();
  });
});

describe("DocumentChecklist — GĐ1b: Xác nhận kiểm tra = lô MỘT hồ sơ", () => {
  const P = "http://localhost:8000/api/admissions/documents/bulk-verify";

  it("bấm Xác nhận kiểm tra ⇒ xem trước lô với profile_ids = [id hồ sơ]; KHÔNG gọi duyệt từng giấy", async () => {
    const thanXemTruoc: unknown[] = [];
    let soDuyetLe = 0;
    server.use(
      http.post(`${P}/preview`, async ({ request }) => {
        thanXemTruoc.push(await request.json());
        return HttpResponse.json(
          {
            batch_id: "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60",
            expires_at: "2026-11-18T08:30:00Z",
            counts: { profiles: 1, documents: 2, required: 2, optional: 0 },
            items: [
              { profile_id: 42, document_row_id: 1, document_type_code: "HOC_BA", expected_row_version: 1, is_mandatory: true },
              { profile_id: 42, document_row_id: 2, document_type_code: "CCCD", expected_row_version: 1, is_mandatory: true },
            ],
            excluded: [],
          },
          { status: 201 },
        );
      }),
      http.patch(/\/documents\/[^/]+\/verify-format$/, () => {
        soDuyetLe++;
        return HttpResponse.json({ id: 42 });
      }),
    );
    const profile = buildProfile([
      { code: "HOC_BA", label: "Học bạ", status: "paper_submitted", is_mandatory: true, requires_upload: false, can_verify: true },
      { code: "CCCD", label: "Căn cước", status: "paper_submitted", is_mandatory: true, requires_upload: false, can_verify: true },
    ]);
    await openAndRender(profile);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /xác nhận kiểm tra/i }));
    const hop = await screen.findByRole("dialog");
    await user.click(within(hop).getByRole("button", { name: "Xem trước" }));
    expect(await within(hop).findByTestId("so-giay-se-duyet")).toHaveTextContent("2");
    expect(thanXemTruoc).toEqual([{ profile_ids: [42], include_optional: false }]);
    await waitFor(() => expect(soDuyetLe).toBe(0));
    sessionStorage.clear();
  });

  it("giấy chờ kiểm thiếu hình thức lúc nhận ⇒ ghi 'Chưa ghi hình thức lúc nhận', không chọn sẵn photo", async () => {
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "paper_submitted",
        is_mandatory: true,
        requires_upload: false,
        can_verify: true,
        actual_submission_format: null,
      },
    ]);
    await openAndRender(profile);
    expect(screen.getByTestId("thieu-hinh-thuc-HOC_BA")).toHaveTextContent("Chưa ghi hình thức lúc nhận");
    expect(screen.queryByText(/photo|chụp/i)).toBeNull();
  });

  it("Từ chối gửi expected_row_version của giấy (hộp GĐ1b)", async () => {
    const than: unknown[] = [];
    server.use(
      http.post("http://localhost:8000/api/admissions/42/documents/HOC_BA/reject", async ({ request }) => {
        than.push(await request.json());
        return HttpResponse.json({
          code: "HOC_BA",
          status: "rejected",
          rejection_reason: "mờ",
          rejected_at: null,
          rejected_by_id: 2,
          document_row_id: 9,
          row_version: 5,
        });
      }),
    );
    const profile = buildProfile([
      {
        code: "HOC_BA",
        label: "Học bạ",
        status: "uploaded",
        is_mandatory: true,
        requires_upload: true,
        can_reject: true,
        document_row_id: 9,
        row_version: 4,
      },
    ]);
    await openAndRender(profile);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Từ chối giấy Học bạ" }));
    const hop = await screen.findByRole("dialog");
    await user.type(within(hop).getByLabelText(/Lý do từ chối/), "mờ");
    await user.click(within(hop).getByRole("button", { name: "Từ chối" }));
    await waitFor(() => expect(than).toHaveLength(1));
    expect(than[0]).toEqual({ reason: "mờ", expected_row_version: 4, unknown_submitter_ack: false });
  });
});
