/**
 * DocumentChecklist permission gating (PR #5 review follow-up).
 *
 * The Step 7 checklist used to surface "Xác nhận kiểm tra" and per-row
 * reject buttons based purely on doc.status. With backend-computed
 * `can_verify` / `can_reject` flags now authoritative, officers (who
 * can't verify per Casbin + service guard) must not see those buttons
 * even when a doc is uploaded/paper-submitted.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils/test-utils";
import userEvent from "@testing-library/user-event";

import { DocumentChecklist } from "./DocumentChecklist";

vi.mock("@/hooks/admissions", () => ({
  useVerifyDocument: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  useRejectDocument: () => ({ mutate: vi.fn(), isPending: false }),
}));

type DocRow = {
  code: string;
  label: string;
  status: string;
  is_mandatory: boolean;
  requires_upload: boolean;
  can_verify?: boolean;
  can_reject?: boolean;
  verified_format?: string | null;
  actual_submission_format?: string | null;
  submission_format?: string | null;
  file_path?: string | null;
};

function buildProfile(docs: DocRow[]) {
  return {
    id: 42,
    status: "submitted",
    documents_checklist: docs,
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
      screen.queryByRole("button", { name: /từ chối tài liệu/i })
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
      await screen.findByRole("button", { name: /từ chối tài liệu/i })
    ).toBeInTheDocument();
  });
});
