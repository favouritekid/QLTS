#!/usr/bin/env python3
"""Planner + cổng nghiệm thu cho `nightly-regression.yml`.

Vì sao tồn tại
--------------
Sáu bước E2E từng gác bằng::

    if: always() && (github.event.inputs.suites == 'all'
                     || contains(github.event.inputs.suites, 'lead'))

Trên ``schedule`` thì ``github.event.inputs`` là ``null``; GitHub ép ``null``
thành chuỗi rỗng, nên ``null == 'all'`` sai và ``contains('', 'lead')`` cũng
sai. Cả sáu bước **skipped**, job vẫn **success**. Đo thật: 15/15 lượt
``schedule`` từ 2026-08-23 tới 2026-09-06 đều ``success`` với E2E chạy=0,
skipped=6, đỏ=0. Mười lăm đêm không có một ca E2E nào chạy mà không cổng nào
kêu.

Chương trình này thay quyết định ấy bằng hai lệnh:

``plan``    quyết định suite nào chạy, ghi ``$GITHUB_OUTPUT`` + tệp kế hoạch.
``verify``  đối chiếu kết quả THẬT của sáu bước với kế hoạch; đỏ nếu lệch.

Ràng buộc thiết kế
------------------
* Giá trị người dùng nhập KHÔNG bao giờ đi qua ``argv``, chỉ qua ``env``. Nhờ
  vậy thân ``run:`` của workflow không chứa một ``${{`` nào — không có đường
  nội suy vào shell.
* ``verify`` đọc **kỳ vọng** từ tệp kế hoạch, KHÔNG từ ``steps.plan.outputs``.
  Nếu đọc từ outputs thì tháo dây ``outputs`` làm cả hai vế cùng rỗng và phép
  so ``∅ == ∅`` lại xanh — đúng lớp lỗi đang vá.
* Dùng ``steps.<id>.outcome``, KHÔNG dùng ``conclusion``: ``conclusion`` đã bị
  ``continue-on-error`` bóp méo, nên một dòng YAML biến cổng thành fail-open.

Mã thoát: 0 đạt · 1 vi phạm hợp đồng · 2 đầu vào/môi trường hỏng.
"""

import argparse
import json
import os
import sys

SCHEMA_VERSION = 1

#: NGUỒN CHUẨN DUY NHẤT của census suite. Mọi thứ khác — `id` của bước, tên
#: output, dòng `run` — đều phải suy ra từ đây và được test đối chiếu ngược.
#: Giữ đúng thứ tự khai báo: `selected` phải ổn định để so sánh được, nếu
#: không thì gõ `smoke,lead` và `lead,smoke` cho hai chuỗi khác nhau và cổng
#: đỏ giả.
SUITES = {
    "lead": {
        "spec": ("src/test/e2e/lead-workflow.spec.ts",),
        "project": "e2e-workflow",
    },
    "admission": {
        "spec": ("src/test/e2e/admission-lifecycle.spec.ts",),
        "project": "e2e-workflow",
    },
    "finance": {
        "spec": ("src/test/e2e/finance-lifecycle.spec.ts",),
        "project": "e2e-workflow",
    },
    "bugfix": {
        "spec": ("src/test/e2e/bugfix-regression.spec.ts",),
        "project": "e2e-workflow",
    },
    "unified": {
        "spec": ("src/test/e2e/lead-to-admission-workflow.spec.ts",),
        "project": "e2e-workflow",
    },
    # ⚠️ `smoke` cố ý KHÁC ba điểm so với năm suite kia: chạy HAI spec, dùng
    # `--project=chromium`, và KHÔNG ghim `--workers=1`. Đừng "chuẩn hoá cho
    # đều" — đó là hành vi đã ship, không phải sơ suất.
    "smoke": {
        "spec": (
            "src/test/e2e/smoke-all-pages.spec.ts",
            "src/test/e2e/admission-ui-smoke.spec.ts",
        ),
        "project": "chromium",
    },
}

#: Tiền tố `id` của bước và tên output — MỘT phép biến đổi duy nhất, dùng ở
#: cả workflow lẫn test. Không có bảng ánh xạ nào khác; mọi bảng ánh xạ đều là
#: một chỗ để trôi.
TIEN_TO_ID = "e2e_"

TAT_CA = "all"

#: Giá trị `outcome` mà GitHub sinh ra. Bất cứ thứ gì ngoài tập này đều bị coi
#: là không hiểu được, và không hiểu được thì ĐỎ.
OUTCOME_HOP_LE = frozenset({"success", "failure", "cancelled", "skipped"})

#: Cắt bớt giá trị người dùng nhập trước khi đưa vào thông điệp lỗi. Một input
#: 10.000 ký tự làm log annotation của GitHub vô dụng.
DAI_TOI_DA_TRICH = 200


class LoiKeHoach(Exception):
    """Đầu vào không đủ tin cậy để lập kế hoạch, hoặc hợp đồng bị vi phạm."""


def id_buoc(ten_suite: str) -> str:
    """`lead` -> `e2e_lead`. Vừa là `id` của bước, vừa là tên output."""
    return TIEN_TO_ID + ten_suite


def _trich(gia_tri) -> str:
    """`repr` đã cắt ngắn — dùng cho MỌI giá trị do người dùng điều khiển."""
    s = repr(gia_tri)
    return s if len(s) <= DAI_TOI_DA_TRICH else s[:DAI_TOI_DA_TRICH] + "…(đã cắt)"


# ---------------------------------------------------------------------------
# 1. Chọn suite — hàm THUẦN, không I/O, không đọc env
# ---------------------------------------------------------------------------
def chon_suite(event_name, suites_raw):
    """Trả về tuple suite theo THỨ TỰ KHAI BÁO, hoặc ném `LoiKeHoach`.

    ⚠️ `event_name` là tham số BẮT BUỘC, không phải trang trí. Trên `schedule`,
    biểu thức `${{ github.event.inputs.suites }}` render thành chuỗi RỖNG — y
    hệt ca người dùng bấm dispatch rồi xoá trắng ô nhập. Hai ca ấy phải xử lý
    NGƯỢC NHAU (schedule ⇒ đủ sáu; dispatch rỗng ⇒ từ chối). Không có
    `event_name` thì không phân biệt được, và ta chỉ dời nguyên cái lỗi cũ từ
    YAML sang Python.
    """
    if not isinstance(event_name, str) or not event_name:
        raise LoiKeHoach(
            "thiếu tên sự kiện — không thể phân biệt `schedule` (đủ sáu suite) "
            "với `workflow_dispatch` ô nhập rỗng (từ chối)"
        )

    tho = "" if suites_raw is None else str(suites_raw)
    rong = tho.strip() == ""

    if event_name == "schedule":
        if not rong:
            # Schedule KHÔNG mang input. Nhận được giá trị nghĩa là dây nối
            # sai — fail-closed thay vì đoán ý.
            raise LoiKeHoach(
                "sự kiện `schedule` không mang input nhưng nhận được "
                "suites=%s — dây nối trong workflow đang sai" % _trich(tho)
            )
        return tuple(SUITES)

    if event_name != "workflow_dispatch":
        # Allowlist ĐÓNG. Không có nhánh `else: đủ sáu` — một nhánh như thế
        # biến mọi sự kiện lạ thành "chạy tất", che mất việc dây nối sai.
        raise LoiKeHoach(
            "sự kiện không được hỗ trợ: %s (chỉ `schedule` và "
            "`workflow_dispatch`)" % _trich(event_name)
        )

    if rong:
        raise LoiKeHoach(
            "`workflow_dispatch` với ô `suites` rỗng — hãy nhập `all` hoặc một "
            "danh sách suite. Rỗng KHÔNG được ngầm hiểu là `all`: đó chính là "
            "kiểu suy diễn đã làm mười lăm đêm nightly xanh giả."
        )

    khuc = tho.split(",")
    da_thay = []
    for phan in khuc:
        token = phan.strip()
        if token == "":
            raise LoiKeHoach(
                "danh sách suite có token rỗng (dấu phẩy thừa): %s" % _trich(tho)
            )
        if token == TAT_CA:
            if len(khuc) != 1:
                raise LoiKeHoach(
                    "`all` phải đứng MỘT MÌNH, nhận %s. Muốn chạy tất cả thì "
                    "để đúng `all`; muốn chạy tập con thì bỏ `all` đi. Gộp hai "
                    "nghĩa vào một đầu vào là cách chắc chắn để gõ sai mà "
                    "không ai biết." % _trich(tho)
                )
            return tuple(SUITES)
        if token not in SUITES:
            # So khớp BẰNG NHAU. Không `in`, không `startswith`, không
            # `contains` — `contains()` của GitHub cho `leadership` khớp
            # `lead`, và đó là quả bom thứ hai đang ngủ trong workflow cũ.
            if token.lower() in SUITES:
                raise LoiKeHoach(
                    "token phải viết thường: %s → %r. (`contains()` của GitHub "
                    "không phân biệt hoa thường; planner này thì CÓ, cố ý.)"
                    % (_trich(token), token.lower())
                )
            raise LoiKeHoach(
                "token suite lạ: %s. Hợp lệ: %s"
                % (_trich(token), ", ".join(SUITES))
            )
        if token in da_thay:
            raise LoiKeHoach(
                "token suite trùng lặp: %r trong %s. `set()` sẽ nuốt im lặng "
                "chỗ này, nên phải chặn tường minh." % (token, _trich(tho))
            )
        da_thay.append(token)

    # Trả theo thứ tự KHAI BÁO, không theo thứ tự người dùng gõ.
    return tuple(s for s in SUITES if s in da_thay)


# ---------------------------------------------------------------------------
# 2. Đối chiếu kết quả thật — hàm THUẦN
# ---------------------------------------------------------------------------
def kiem_outcome(ke_hoach, steps):
    """Trả về danh sách vi phạm (rỗng = đạt). Không ném cho ca hợp đồng.

    `ke_hoach` là dict đã đọc từ tệp kế hoạch; `steps` là dict đã parse từ
    `toJSON(steps)` của GitHub.
    """
    vi_pham = []

    chon = ke_hoach.get("selected")
    tat_ca = ke_hoach.get("all_suites")
    dem = ke_hoach.get("selected_count")

    if not isinstance(chon, list) or not isinstance(tat_ca, list):
        return ["tệp kế hoạch thiếu `selected`/`all_suites` hoặc sai kiểu"]
    if list(tat_ca) != list(SUITES):
        vi_pham.append(
            "`all_suites` trong kế hoạch (%s) khác census của planner (%s) — "
            "kế hoạch được dựng bởi một bản planner khác" % (tat_ca, list(SUITES))
        )
    if dem != len(chon):
        vi_pham.append(
            "`selected_count`=%r nhưng `selected` có %d phần tử" % (dem, len(chon))
        )
    la = [s for s in chon if s not in SUITES]
    if la:
        vi_pham.append("`selected` chứa suite không có thật: %s" % la)

    # V2 — bất biến GỐC. Giữ nó kể cả khi trông thừa: nếu cổng chỉ so hai tập
    # mà cả hai cùng rỗng thì `∅ == ∅` xanh, và ta quay lại đúng mười lăm đêm
    # vừa rồi.
    if not chon:
        vi_pham.append(
            "KHÔNG suite nào được chọn (selected_count=0). Job này tồn tại để "
            "chạy E2E; không chạy gì mà vẫn xanh là chính lỗi đang được vá."
        )

    tap_chon = set(chon)
    bang = []
    for suite in SUITES:
        sid = id_buoc(suite)
        buoc = steps.get(sid)
        if not isinstance(buoc, dict):
            # Bước bị gỡ `id`, bị xoá, hoặc job bị huỷ trước khi bước tồn tại.
            # `toJSON(steps)` chỉ chứa bước CÓ `id`, nên ca này bắt được cả
            # việc gỡ `id` lúc chạy mà không cần ca kiểm tĩnh riêng.
            vi_pham.append(
                "thiếu bước `%s` trong `steps` — bước bị xoá, bị gỡ `id`, hoặc "
                "job dừng trước khi tới nó" % sid
            )
            bang.append((suite, suite in tap_chon, None, "(vắng mặt)"))
            continue
        outcome = buoc.get("outcome")
        if outcome not in OUTCOME_HOP_LE:
            vi_pham.append(
                "bước `%s` có outcome không hiểu được: %s — fail-closed"
                % (sid, _trich(outcome))
            )
            bang.append((suite, suite in tap_chon, None, str(outcome)))
            continue
        da_chay = outcome != "skipped"
        bang.append((suite, suite in tap_chon, da_chay, outcome))
        if suite in tap_chon:
            if outcome != "success":
                vi_pham.append(
                    "suite `%s` ĐƯỢC CHỌN nhưng outcome=`%s` (cần `success`)"
                    % (suite, outcome)
                )
        else:
            if outcome != "skipped":
                vi_pham.append(
                    "suite `%s` KHÔNG được chọn nhưng outcome=`%s` (cần "
                    "`skipped`) — dây nối đang đấu chéo" % (suite, outcome)
                )

    # Phép so cấp TẬP HỢP, khác cấp phần tử ở trên: nó bắt ca hai lỗi bù trừ
    # nhau về số lượng.
    thuc_te = {s for s, _, chay, out in bang if out == "success"}
    if thuc_te != tap_chon:
        vi_pham.append(
            "tập suite THÀNH CÔNG (%s) khác tập DỰ KIẾN (%s)"
            % (sorted(thuc_te), sorted(tap_chon))
        )

    return vi_pham


def bang_doi_chieu(ke_hoach, steps):
    """Bảng expected/actual/outcome theo TỪNG suite — đọc log lúc 2h sáng."""
    tap_chon = set(ke_hoach.get("selected") or [])
    dong = ["  %-11s %-9s %-9s %s" % ("suite", "expected", "actual", "outcome"),
            "  %-11s %-9s %-9s %s" % ("-" * 11, "-" * 9, "-" * 9, "-" * 10)]
    for suite in SUITES:
        buoc = steps.get(id_buoc(suite))
        outcome = buoc.get("outcome") if isinstance(buoc, dict) else None
        mong = "RUN" if suite in tap_chon else "SKIP"
        if outcome is None:
            that, hien = "?", "(vắng mặt)"
        else:
            that = "SKIP" if outcome == "skipped" else "RUN"
            hien = str(outcome)
        co = "" if (mong == that and (mong == "SKIP" or outcome == "success")) else "   <-- lệch"
        dong.append("  %-11s %-9s %-9s %-10s%s" % (suite, mong, that, hien, co))
    return "\n".join(dong)


# ---------------------------------------------------------------------------
# 3. I/O
# ---------------------------------------------------------------------------
def ghi_github_output(cap):
    """Ghi vào `$GITHUB_OUTPUT`. Thiếu biến ⇒ ĐỎ, không im lặng bỏ qua.

    Khác `deploy_change_classifier._write_github_output` một điểm cố ý: ở đó
    thiếu `GITHUB_OUTPUT` chỉ `return` vì nó còn ghi artifact. Ở đây thiếu
    output nghĩa là cả sáu bước E2E skip — tức đúng cái bug đang vá, chỉ khoác
    áo mới. Nên nó phải nổ.
    """
    duong = os.environ.get("GITHUB_OUTPUT")
    if not duong:
        raise LoiKeHoach(
            "thiếu biến `GITHUB_OUTPUT` — planner không có nơi công bố kế "
            "hoạch, và không có kế hoạch thì cả sáu bước E2E sẽ skip"
        )
    for k, v in cap.items():
        # Mọi giá trị ở đây đều sinh từ enum đóng nên không thể chứa xuống
        # dòng. Khẳng định vẫn để lại: nó biến "không echo đầu vào người dùng"
        # từ một sự tình cờ thành một bất biến được kiểm.
        if "\n" in str(v) or "\r" in str(v):
            raise LoiKeHoach("giá trị output chứa xuống dòng: %r=%s" % (k, _trich(v)))
    with open(duong, "a", encoding="utf-8") as f:
        for k, v in cap.items():
            f.write("%s=%s\n" % (k, v))


def _doc_json(duong, nhan):
    try:
        with open(duong, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise LoiKeHoach("%s không tồn tại: %s — planner chưa chạy?" % (nhan, duong))
    except (OSError, ValueError) as exc:
        raise LoiKeHoach("%s không đọc/parse được: %s" % (nhan, exc))


def _plan_command(args):
    event_name = os.environ.get("QLTS_EVENT_NAME")
    suites_raw = os.environ.get("QLTS_SUITES_RAW")
    chon = chon_suite(event_name, suites_raw)

    cap = {id_buoc(s): ("true" if s in chon else "false") for s in SUITES}
    cap["selected"] = ",".join(chon)
    cap["selected_count"] = str(len(chon))
    ghi_github_output(cap)

    ke_hoach = {
        "schema_version": SCHEMA_VERSION,
        "event_name": event_name,
        "suites_raw": suites_raw,
        "selected": list(chon),
        "selected_count": len(chon),
        "all_suites": list(SUITES),
    }
    with open(args.plan_file, "w", encoding="utf-8") as f:
        json.dump(ke_hoach, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    print("Nightly plan: %d/%d suite — %s"
          % (len(chon), len(SUITES), ", ".join(chon)))
    return 0


def _verify_command(args):
    ke_hoach = _doc_json(args.plan_file, "tệp kế hoạch")
    tho = os.environ.get("QLTS_STEPS_JSON")
    if not tho:
        raise LoiKeHoach(
            "thiếu `QLTS_STEPS_JSON` — cổng không nhận được kết quả của các "
            "bước; dây nối `toJSON(steps)` đã bị tháo"
        )
    try:
        steps = json.loads(tho)
    except ValueError as exc:
        raise LoiKeHoach("`QLTS_STEPS_JSON` không parse được: %s" % exc)
    if not isinstance(steps, dict):
        raise LoiKeHoach("`QLTS_STEPS_JSON` không phải object: %s" % _trich(type(steps)))

    vi_pham = kiem_outcome(ke_hoach, steps)
    bang = bang_doi_chieu(ke_hoach, steps)
    if vi_pham:
        print("::error::Cổng nightly ĐỎ — %d vi phạm." % len(vi_pham))
        for v in vi_pham:
            print("  - %s" % v)
        print()
        print(bang)
        print()
        print("  selected (kế hoạch): %s" % (",".join(ke_hoach.get("selected") or []) or "(rỗng)"))
        print("  selected_count     : %s" % ke_hoach.get("selected_count"))
        return 1
    print("Cổng nightly ĐẠT — %d suite chạy đúng kế hoạch."
          % len(ke_hoach.get("selected") or []))
    print(bang)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    # ⚠️ KHÔNG có tham số nào mang giá trị `suites`. Nếu có, `run:` buộc phải
    # viết `--suites "${{ github.event.inputs.suites }}"` — nội suy giá trị
    # người dùng thẳng vào shell. Giá trị chỉ đi qua `env:`.
    p = sub.add_parser("plan", help="quyết định suite nào chạy")
    p.add_argument("--plan-file", required=True)
    p.set_defaults(handler=_plan_command)

    v = sub.add_parser("verify", help="đối chiếu kết quả thật với kế hoạch")
    v.add_argument("--plan-file", required=True)
    v.set_defaults(handler=_verify_command)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except LoiKeHoach as exc:
        print("::error::%s" % exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
