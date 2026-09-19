// src/lib/auth/open-redirect.contract.test.ts
/**
 * Open redirect qua CHUẨN HOÁ DOT-SEGMENT.
 *
 * Lỗ hổng không nằm ở một hàm nào, mà ở KHE giữa hai hàm:
 *
 *   `isValidRedirect` lọc CHUỖI THÔ  →  `withSr`/`stripSr`/`stripRsc` CHUẨN HOÁ
 *
 * `/..//evil.example` đi qua được mọi phép lọc thô (bắt đầu `/`, không `//`,
 * không `:`, không `\`, không `%2f`), rồi `new URL(x, nền).pathname` bỏ đoạn
 * `..` và cho ra `//evil.example`. Một chuỗi bắt đầu bằng `//` là URL
 * **protocol-relative**: `location.replace("//evil.example")` rời khỏi site.
 *
 * ⚠️ `%2f` bị chặn nhưng `%2e` thì KHÔNG — mà WHATWG URL coi `%2e` là `.` khi
 * bỏ dot-segment, nên `/%2e%2e//evil.example` là đúng cùng một lỗ viết khác đi.
 *
 * Vì thế bộ ca này KHÔNG kiểm từng hàm rời rạc mà kiểm CẢ CHUỖI, và đo bằng
 * thứ trình duyệt thật sự làm: phân giải chuỗi trả về trên một origin thật rồi
 * hỏi `origin` có đổi không. Kiểm `startsWith("//")` một mình là chưa đủ — nó
 * là dấu hiệu, còn `origin` mới là hậu quả.
 */
import { describe, it, expect } from "vitest";

import { isValidRedirect, stripRsc } from "./login-redirect";
import { SR_MAX, parseSr, stripSr, withSr } from "./sr-marker";

/** Origin của chính site — dùng để hỏi "chuỗi này có đưa ta đi đâu không". */
const NHA = "https://qlts.example";

/** Trình duyệt sẽ tới origin nào khi `location.replace(duongDan)`. */
function origindDich(duongDan: string): string {
  try {
    return new URL(duongDan, NHA).origin;
  } catch {
    // Không phân giải được ⇒ không điều hướng đi đâu ⇒ coi như ở nhà.
    return NHA;
  }
}

/**
 * Ba tải trọng bắt buộc của cổng rà soát, cộng các biến thể cùng họ.
 *
 * Mỗi dòng là MỘT cách viết khác nhau của cùng một ý: nhét một đoạn sẽ BỐC HƠI
 * lúc chuẩn hoá, để phần còn lại tụt xuống thành `//`.
 */
const TAI_TRONG_THOAT_SITE = [
  "/..//evil.example",
  "/.//evil.example",
  "/%2e%2e//evil.example",
  // Cùng họ, khác cách viết — nếu bản vá chỉ khớp chuỗi thì những dòng này lọt.
  "/%2E%2E//evil.example",
  "/a/..//evil.example",
  "/./..//evil.example",
  "/..//evil.example?tab=ho-so#muc-2",
];

/**
 * Đường dẫn LÀNH phải tiếp tục đi qua.
 *
 * Có cả `/a/../b`: nó CHỨA `..` nhưng chuẩn hoá ra `/b` — nội bộ, vô hại. Giữ
 * nó ở đây để bản vá không trượt thành "cấm mọi dấu chấm", một luật thô vừa
 * chặn nhầm vừa không giải quyết `%2e`.
 */
const DUONG_DAN_LANH = [
  "/leads",
  "/leads?q=a:b",
  "/finance?from=2026-06-24T10:00:00",
  "/leads?tab=ho-so&page=3#muc-2",
  "/a/../b",
  "/ho-so/123",
];

describe("isValidRedirect — lọc phải nhìn thấy bản ĐÃ CHUẨN HOÁ", () => {
  it.each(TAI_TRONG_THOAT_SITE)("CHẶN %s", (tai) => {
    expect(isValidRedirect(tai)).toBe(false);
  });

  it.each(DUONG_DAN_LANH)("vẫn CHO QUA %s", (duong) => {
    expect(isValidRedirect(duong)).toBe(true);
  });
});

describe("chuỗi thực tế: isValidRedirect → withSr → điều hướng", () => {
  it.each(TAI_TRONG_THOAT_SITE)(
    "%s không bao giờ rời khỏi site, dù đi lối nào",
    (tai) => {
      // Lối ĐÚNG: guard canonical chặn từ đầu, bootstrap dùng target mặc định.
      expect(isValidRedirect(tai)).toBe(false);

      // Lối SAI: giả sử một chỗ nào đó quên gọi guard và đưa thẳng vào withSr.
      // Đây là chặn cuối — đầu ra KHÔNG ĐƯỢC bắt đầu bằng `//`, và quan trọng
      // hơn, không được đổi origin.
      const sauWithSr = withSr(tai, 1);
      expect(sauWithSr.startsWith("//")).toBe(false);
      expect(origindDich(sauWithSr)).toBe(NHA);

      // Nhánh rời vòng cứu phiên dùng stripSr — cùng khuôn, cùng lỗ.
      const sauStripSr = stripSr(tai);
      expect(sauStripSr.startsWith("//")).toBe(false);
      expect(origindDich(sauStripSr)).toBe(NHA);

      // stripRsc ở proxy/server cũng cùng khuôn.
      const sauStripRsc = stripRsc(tai);
      expect(sauStripRsc.startsWith("//")).toBe(false);
      expect(origindDich(sauStripRsc)).toBe(NHA);
    },
  );
});

describe("bất biến: ba hàm chuẩn hoá không bao giờ trả chuỗi bắt đầu `//`", () => {
  // Gộp cả tải trọng lẫn đường lành: bất biến phải đúng trên MỌI đầu vào, kể
  // cả đầu vào không ai ngờ tới.
  const MOI_DAU_VAO = [
    ...TAI_TRONG_THOAT_SITE,
    ...DUONG_DAN_LANH,
    "//evil.example",
    "///evil.example",
    "/..//..//evil.example",
    "/",
    "",
  ];

  it.each(MOI_DAU_VAO)("withSr(%j) không bắt đầu bằng `//`", (dauVao) => {
    expect(withSr(dauVao, 1).startsWith("//")).toBe(false);
  });

  it.each(MOI_DAU_VAO)("stripSr(%j) không bắt đầu bằng `//`", (dauVao) => {
    expect(stripSr(dauVao).startsWith("//")).toBe(false);
  });

  it.each(MOI_DAU_VAO)("stripRsc(%j) không bắt đầu bằng `//`", (dauVao) => {
    expect(stripRsc(dauVao).startsWith("//")).toBe(false);
  });
});

/**
 * ─────────────────────────────────────────────────────────────────────────────
 * Chặn cuối của `withSr` phải GIỮ `_sr` — nhóm bất biến ngay trên KHÔNG canh
 * được chỗ này.
 *
 * `expect(withSr(x, 1).startsWith("//")).toBe(false)` chỉ hỏi đúng một câu:
 * "có rời khỏi site không". Một đột biến đổi chặn cuối thành
 * `return DUONG_AN_TOAN;` — trả trơ `/`, bỏ `?_sr=` — ĐI QUA trọn vẹn nhóm đó:
 * `/` không bắt đầu bằng `//`, và `origindDich("/")` vẫn là nhà. Bộ ca cũ mù
 * đúng chỗ này.
 *
 * Mà mất `_sr` là mất bộ đếm vòng: lượt sau `parseSr` đọc ra 0, nắp `SR_MAX`
 * không bao giờ đóng, và ta đổi một lỗ hổng open-redirect lấy đúng cái vòng
 * lặp `/session-refresh` đang phải chữa.
 *
 * Hai nhóm ca dưới đây tách đôi có chủ đích, mỗi ca vi phạm MỘT bất biến:
 *
 *   A. GIÁ TRỊ TRẢ VỀ chính xác — hợp đồng đầy đủ của chặn cuối, đọc bằng mắt;
 *   B. BỘ ĐẾM SỐNG SÓT — đo qua `parseSr`, không so chuỗi. Ca B chỉ đỏ khi mất
 *      `_sr`, và vẫn xanh nếu ai đó đổi CÁCH VIẾT của đường an toàn. Nên chỉ A
 *      đỏ ⇒ đổi cách viết; A và B cùng đỏ ⇒ mất nắp.
 */
describe("chặn cuối `withSr`: rơi về đường an toàn nhưng GIỮ bộ đếm `_sr`", () => {
  it.each(TAI_TRONG_THOAT_SITE)(
    "A. withSr(%j, 1) trả ĐÚNG `/?_sr=1`",
    (tai) => {
      expect(withSr(tai, 1)).toBe("/?_sr=1");
    },
  );

  it.each(TAI_TRONG_THOAT_SITE)(
    "B. bộ đếm sống sót: parseSr(withSr(%j, 1)) là 1",
    (tai) => {
      // Đo bằng chính hàm ĐỌC mà nắp dựa vào, không bằng so chuỗi: nắp chỉ
      // đóng được khi `parseSr` đọc lại được số vòng `withSr` vừa ghi.
      expect(parseSr(withSr(tai, 1))).toBe(1);
    },
  );

  it.each(TAI_TRONG_THOAT_SITE)(
    "B'. ở NẮP: parseSr(withSr(%j, 5)) là SR_MAX",
    (tai) => {
      // `5` vượt nắp, nên câu hỏi ở đây là "có kẹp về nắp không" chứ không phải
      // "nắp bằng mấy" — vì thế kỳ vọng viết bằng hằng `SR_MAX`, để ca này
      // không đổi màu khi ai đó chỉnh nắp.
      expect(parseSr(withSr(tai, 5))).toBe(SR_MAX);
    },
  );
});

describe("hợp đồng cũ không được vỡ vì bản vá này", () => {
  it("withSr GIỮ query nghiệp vụ và hash của đường dẫn lành", () => {
    const ketQua = withSr("/leads?tab=ho-so&page=3#muc-2", 1);
    expect(ketQua.startsWith("/leads?")).toBe(true);
    expect(ketQua).toContain("tab=ho-so");
    expect(ketQua).toContain("page=3");
    expect(ketQua).toContain("_sr=1");
    expect(ketQua.endsWith("#muc-2")).toBe(true);
  });

  it("stripSr GỠ `_sr` mà không mất query/hash", () => {
    const ketQua = stripSr("/leads?tab=ho-so&_sr=2&page=3#muc-2");
    expect(ketQua).not.toContain("_sr");
    expect(ketQua).toContain("tab=ho-so");
    expect(ketQua).toContain("page=3");
    expect(ketQua.endsWith("#muc-2")).toBe(true);
  });

  it("`/a/../b` là ĐƯỜNG LÀNH: được qua, và chuẩn hoá về `/b`", () => {
    expect(isValidRedirect("/a/../b")).toBe(true);
    expect(withSr("/a/../b", 0)).toBe("/b?_sr=0");
  });

  it("auth path vẫn bị chặn, kể cả khi giấu sau dot-segment", () => {
    expect(isValidRedirect("/login")).toBe(false);
    expect(isValidRedirect("/session-refresh")).toBe(false);
    // Bản lọc thô cũ bỏ sót dòng này: chuẩn hoá ra `/login`.
    expect(isValidRedirect("/a/../login")).toBe(false);
  });
});
