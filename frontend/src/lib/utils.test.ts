// src/lib/utils.test.ts
/**
 * Hợp đồng của `resolveSafeUrl` — guard DUY NHẤT cho liên kết do máy chủ cấp.
 *
 * Trước bộ ca này, `isSafeUrl` có **0 tệp test, 0 ca**: khe chưa canh là TOÀN
 * BỘ hàm, không phải một biến thể.
 *
 * Bất biến nghiệm thu KHÔNG phải "hàm trả true" mà là: **đích thật sự dùng để
 * điều hướng có origin được phép**. Vì thế mỗi ca đo trên GIÁ TRỊ TRẢ VỀ, rồi
 * phân giải lại chính giá trị đó trên một origin thật và hỏi origin có đổi
 * không — giống hệt việc trình duyệt sẽ làm.
 */
import { describe, it, expect } from "vitest";

import { resolveSafeUrl, isSafeUrl } from "./utils";

/** Origin của chính site, dùng để hỏi "đích này đưa ta đi đâu". */
const NHA = "https://qlts.example";

/** Trình duyệt sẽ tới origin nào khi điều hướng tới `dich`. */
function originDich(dich: string): string {
  try {
    return new URL(dich, NHA).origin;
  } catch {
    return NHA;
  }
}

/**
 * Tải trọng phải bị CHẶN. Mỗi dòng là một cách thoát site khác nhau — không
 * phải biến thể viết khác của cùng một cách.
 */
const PHAI_CHAN: Array<[string, string]> = [
  ["TAB nội bộ (parser xoá rồi thành `//`)", "/\t/evil.example"],
  ["LF nội bộ", "/\n/evil.example"],
  ["CR nội bộ", "/\r/evil.example"],
  ["một backslash (WHATWG coi như `/`)", "/\\evil.example"],
  ["domain nối đuôi", "https://qlts.example.evil.com/x"],
  ["userinfo `@`", "https://qlts.example@evil.com/x"],
  ["scheme-relative", "//evil.example/x"],
  ["scheme-relative ba gạch", "///evil.example/x"],
  ["javascript:", "javascript:alert(1)"],
  ["javascript: sau xuống dòng", "\njavascript:alert(1)"],
  ["data:", "data:text/html,<script>alert(1)</script>"],
  ["vbscript:", "vbscript:msgbox(1)"],
  ["http tuyệt đối khác origin", "http://evil.example/x"],
  ["chuỗi rỗng", ""],
];

/** Đường dẫn LÀNH phải tiếp tục đi qua. */
const PHAI_QUA: Array<[string, string]> = [
  ["đường dẫn thường", "/leads"],
  ["có query", "/leads?tab=ho-so&page=3"],
  ["có hash", "/ho-so/123#muc-2"],
  ["query chứa dấu hai chấm", "/finance?from=2026-06-24T10:00:00"],
  ["gốc", "/"],
];

describe("resolveSafeUrl — CHẶN mọi đường thoát site", () => {
  it.each(PHAI_CHAN)("chặn %s", (_ten, tai) => {
    expect(resolveSafeUrl(tai)).toBeNull();
  });

  it.each(PHAI_CHAN)("%s: `isSafeUrl` cũng phải false", (_ten, tai) => {
    expect(isSafeUrl(tai)).toBe(false);
  });
});

describe("resolveSafeUrl — CHO QUA đường nội bộ, và đích không rời site", () => {
  it.each(PHAI_QUA)("cho qua %s", (_ten, duong) => {
    const dich = resolveSafeUrl(duong);
    expect(dich).not.toBeNull();
    expect(originDich(dich as string)).toBe(NHA);
  });
});

/**
 * Dot-segment — phân biệt HAI ca khác hẳn nhau.
 *
 * ⚠️ Câu "dot-segment không phải lỗ ở sink này" chỉ đúng với **chuỗi GỐC**:
 * `location.href = "/..//x"` để trình duyệt tự phân giải thì host không đổi.
 * Nhưng hàm này trả về bản **ĐÃ CHUẨN HOÁ**, mà `URL.pathname` đã bỏ
 * dot-segment ⇒ `/..//x` thành `//x`, một URL **protocol-relative**. Trả chuỗi
 * đó ra là tự tay tạo lỗ hổng. Bản vá đầu tiên thiếu chặn cuối và **cả NĂM ca
 * dưới đây bắt được nó**: mỗi ca đòi `resolveSafeUrl` trả `null` (không dùng
 * `originDich`). Đo bằng phép kiểm ngược 20-09 — gỡ dòng chặn cuối trong
 * `resolveSafeUrl` ⇒ đúng 5/5 ca này đỏ, tổng 7 đỏ / 52 xanh trên ba tệp.
 *
 * Vì thế:
 *   - chuẩn hoá xong mà tụt xuống `//` ⇒ **CHẶN**;
 *   - chuẩn hoá xong vẫn là đường nội bộ (`/a/../b` → `/b`) ⇒ **CHO QUA**.
 *
 * Ca `/a/../b` giữ lại để bản vá sau không siết nhầm thành "cấm mọi dấu chấm"
 * — luật đó vừa chặn oan, vừa không giải quyết `%2e`.
 */
describe("dot-segment: chặn khi tụt xuống `//`, cho qua khi vẫn nội bộ", () => {
  it.each(["/..//x", "/.//x", "/%2e%2e//x", "/%2E%2E//x", "/a/..//x"])(
    "CHẶN %s (chuẩn hoá ra `//…`)",
    (duong) => {
      expect(resolveSafeUrl(duong)).toBeNull();
    },
  );

  it("CHO QUA `/a/../b` và chuẩn hoá về `/b`", () => {
    expect(resolveSafeUrl("/a/../b")).toBe("/b");
    expect(originDich("/b")).toBe(NHA);
  });
});

describe("hợp đồng của giá trị trả về", () => {
  it("giữ nguyên query và hash", () => {
    expect(resolveSafeUrl("/leads?tab=ho-so&page=3#muc-2")).toBe(
      "/leads?tab=ho-so&page=3#muc-2",
    );
  });

  it("null/undefined trả null, không ném", () => {
    expect(resolveSafeUrl(null)).toBeNull();
    expect(resolveSafeUrl(undefined)).toBeNull();
  });

  it("đích trả về không bao giờ bắt đầu bằng `//`", () => {
    for (const [, tai] of [...PHAI_CHAN, ...PHAI_QUA]) {
      const dich = resolveSafeUrl(tai);
      if (dich !== null) expect(dich.startsWith("//")).toBe(false);
    }
  });
});

/**
 * 🔴 NỀN ẢO KHÔNG ĐƯỢC LÀ THỨ QUYẾT ĐỊNH PHÂN LOẠI.
 *
 * Bản đầu nhận diện "URL tương đối" bằng `resolved.origin === PLACEHOLDER_ORIGIN`.
 * Nền ảo là một origin THẬT theo nghĩa của URL parser, nên một đầu vào TRỎ ĐÍCH
 * DANH tới chính nó cũng thoả điều kiện ấy. Đo bằng URL parser (node v20.20.0):
 *
 *   `//placeholder.invalid/x`        → origin `https://placeholder.invalid`
 *   `https://placeholder.invalid/x`  → origin `https://placeholder.invalid`
 *
 * Cả hai vì thế bị xếp là "tương đối", **đi vòng qua** nhánh kiểm origin API —
 * đúng nhánh mà docstring nói là phải TỪ CHỐI URL tuyệt đối lạ.
 *
 * ⚖️ PHÂN MỨC CHO ĐÚNG, ĐỪNG THỔI LÊN: đích trả về vẫn là `/x`, tức đường NỘI
 * BỘ. Đây **KHÔNG** phải bằng chứng điều hướng ra ngoài site (chặn cuối vẫn
 * đứng, và hàm chỉ trả `pathname+search+hash`). Đây là lỗi **CHẤP NHẬN ĐẦU VÀO
 * / PHÂN LOẠI SAI**: một ngoại lệ thật đối với chính chính sách lọc đã công bố.
 *
 * Hợp đồng: một URL có scheme tường minh, hoặc bắt đầu bằng `//`, là URL TUYỆT
 * ĐỐI — phải đi qua phép kiểm origin API, bất kể host của nó tình cờ là gì.
 * `API_BASE_URL` rỗng trong tệp này ⇒ `apiOrigin()` là `null` ⇒ mong đợi `null`.
 */
describe("phân loại tương đối/tuyệt đối KHÔNG được suy từ origin nền ảo", () => {
  it.each([
    ["scheme-relative trỏ đúng host nền ảo", "//placeholder.invalid/x"],
    ["tuyệt đối trỏ đúng host nền ảo", "https://placeholder.invalid/x"],
    ["tuyệt đối, host nền ảo VIẾT HOA", "https://PLACEHOLDER.INVALID/x"],
    ["tuyệt đối, host nền ảo kèm cổng mặc định", "https://placeholder.invalid:443/x"],
    ["scheme-relative host nền ảo, không path", "//placeholder.invalid"],
  ])("CHẶN %s", (_ten, tai) => {
    expect(resolveSafeUrl(tai)).toBeNull();
  });

  it("đường dẫn tương đối THẬT vẫn đi qua bình thường", () => {
    expect(resolveSafeUrl("/x")).toBe("/x");
    expect(resolveSafeUrl("/leads?tab=a#b")).toBe("/leads?tab=a#b");
  });
});

/**
 * 🔒 ĐẦU VÀO TƯƠNG ĐỐI PHẢI CÓ `/` ĐẦU — khoá bề mặt nhận đầu vào.
 *
 * Đo trên `3fa4ba40`: `isSafeUrl` CŨ **TỪ CHỐI** `leads` (không khớp `//`,
 * không khớp `/`, không khớp tiền tố API/origin ⇒ `return false`). Bản vá phân
 * giải trên nền ảo nên có lúc trả `/leads` — tức **chấp nhận và chuẩn hoá** một
 * thứ hợp đồng cũ từ chối, mà không ai yêu cầu.
 *
 * ⚖️ PHÂN MỨC: đích trả về vẫn NỘI BỘ ⇒ **KHÔNG** phải lỗ thoát site. Đây là
 * **mở rộng hành vi / nới bề mặt nhận đầu vào**. Đừng nâng cấp mức.
 *
 * ✅ HỢP ĐỒNG ĐÃ CHỐT — phương án (a), GIỮ hợp đồng cũ. Ba lý do, không phải
 * sở thích:
 *   1. đây là bản vá **BẢO MẬT**, không phải bản vá tiện dụng; nới bề mặt nhận
 *      đầu vào trong một bản vá bảo mật phải có người yêu cầu tường minh, mà
 *      không có ai yêu cầu;
 *   2. giữ **tương thích hành vi** với `isSafeUrl` cũ ⇒ bản vá không đổi nghĩa
 *      ở bất kỳ đầu vào nào ngoài đúng những ca bảo mật nó sinh ra để chữa;
 *   3. đo 22-09: `normalizeInternalTarget` trên main **cũng từ chối cả ba**
 *      (`isInternalPath` đòi `/` đầu). Chọn (a) làm hai hàm KHỚP nhau ở đây ⇒
 *      xoá một chỗ lệch ngoài ý muốn, thay vì đẻ thêm một chỗ.
 *
 * Đầu ra TRƯỚC khi chốt (đo): `leads`→`/leads`, `?q=x`→`/?q=x`, `#x`→`/#x`.
 * Đầu ra THEO HỢP ĐỒNG: cả ba `null`.
 *
 * URL TUYỆT ĐỐI hợp lệ theo API origin vẫn được nhận — luật này chỉ áp cho
 * nhánh TƯƠNG ĐỐI.
 */
describe("đầu vào tương đối KHÔNG có `/` đầu thì bị TỪ CHỐI", () => {
  it.each([
    ["đường dẫn trần", "leads"],
    ["đường dẫn trần nhiều đoạn", "leads/123"],
    ["chỉ có query", "?q=x"],
    ["chỉ có hash", "#x"],
    ["đường dẫn trần kèm query", "leads?tab=a"],
    ["dấu chấm hiện hành", "./leads"],
    ["lùi một cấp", "../leads"],
  ])("CHẶN %s", (_ten, tai) => {
    expect(resolveSafeUrl(tai)).toBeNull();
  });

  it("`isSafeUrl` giữ đúng hợp đồng cũ cho các đầu vào ấy", () => {
    for (const tai of ["leads", "?q=x", "#x"]) {
      expect(isSafeUrl(tai)).toBe(false);
    }
  });

  it("đường dẫn CÓ `/` đầu vẫn qua — luật này không siết nhầm", () => {
    expect(resolveSafeUrl("/leads")).toBe("/leads");
    expect(resolveSafeUrl("/leads?tab=a")).toBe("/leads?tab=a");
    expect(resolveSafeUrl("/?q=x")).toBe("/?q=x");
    expect(resolveSafeUrl("/#x")).toBe("/#x");
  });
});

/**
/**
 * ⚖️ HỢP ĐỒNG — **KHÔNG nhận URL tuyệt đối**, dù trùng app origin hay API
 * origin.
 *
 * Trước đây `resolveSafeUrl` có một nhánh nhận URL tuyệt đối khi origin trùng
 * origin của API, và guard CŨ (`isSafeUrl` trên main) còn nhận cả URL trùng
 * `window.location.origin`. Cả hai nhánh đã GỠ. Hai lý do kỹ thuật:
 * **fail-closed** (một hình dạng đầu vào hợp lệ thì không còn ngách cho phân
 * loại sai) và **xoá phụ thuộc vào cấu hình origin** (hành vi guard không còn
 * đổi theo `NEXT_PUBLIC_API_URL`).
 *
 * ⚠️ Bộ ca ở ĐÂY chạy với `API_BASE_URL` **RỖNG**; `utils.api-origin.test.ts`
 * chạy cùng hợp đồng với `API_BASE_URL` **CÓ giá trị**. Phải có CẢ HAI cấu
 * hình, vì chính "kết quả giống nhau ở hai cấu hình" mới là thứ chứng minh
 * guard không còn phụ thuộc origin. Một tệp thôi thì không nói được điều đó.
 *
 * ⚖️ Phân mức: đây là **siết bề mặt nhận đầu vào**, và nó có một cái giá đo
 * được — toast `system_alert` không còn nút "View" khi `action_url` là URL
 * tuyệt đối.
 */
describe("URL tuyệt đối bị TỪ CHỐI (API_BASE_URL rỗng)", () => {
  it.each([
    ["thuộc APP origin", "http://localhost:3000/leads?tab=a"],
    ["thuộc APP origin, https", "https://localhost:3000/leads"],
    ["thuộc API origin (giá trị dev mặc định)", "http://localhost:8000/leads"],
    ["origin lạ", "https://evil.example/leads"],
    ["origin lạ, http", "http://evil.example/leads"],
  ])("CHẶN URL tuyệt đối %s", (_ten, tai) => {
    expect(resolveSafeUrl(tai)).toBeNull();
    expect(isSafeUrl(tai)).toBe(false);
  });

  /**
   * ĐỐI CHỨNG DƯƠNG — ca này phải XANH dưới MỌI đột biến hợp lệ. Nó là thứ
   * chặn một bản vá sau siết thành "từ chối tất", vốn cũng làm mọi ca CHẶN ở
   * trên xanh một cách vô nghĩa.
   */
  it("đối chứng dương: `/leads?tab=a` vẫn trả đúng đích", () => {
    expect(resolveSafeUrl("/leads?tab=a")).toBe("/leads?tab=a");
    expect(isSafeUrl("/leads?tab=a")).toBe(true);
  });
});
