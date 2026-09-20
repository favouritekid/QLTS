// src/lib/auth/sr-marker.contract.test.ts
/**
 * Marker `_sr` là thứ DUY NHẤT cho biết đã đi mấy vòng cứu phiên, và sau khi
 * bootstrap cũng ghi nó thì nó nằm trên URL của MỌI lượt làm mới thành công.
 * Hai rủi ro đi kèm, cả hai đều im lặng:
 *
 *  1. thêm marker mà làm hỏng query nghiệp vụ hoặc hash ⇒ người dùng mất chỗ
 *     đang đứng (`?tab=ho-so&page=3#muc-2`) sau mỗi lần cứu phiên;
 *  2. đọc marker sai ⇒ nắp đóng sớm (đá về `/login` khi phiên còn cứu được)
 *     hoặc không bao giờ đóng (đúng vòng lặp đang phải chữa).
 *
 * Ca giữ query/hash đo bằng HAI phép độc lập — một qua `new URL`, một cắt
 * chuỗi thô. Nếu cả hai cùng đi qua `URL` thì một lỗi nằm TRONG `URL` sẽ làm
 * hai phép đo sai theo cùng một kiểu và không phép nào thấy gì.
 */
import { describe, it, expect } from "vitest";

import { SR_MAX, parseSr, stripSr, withSr } from "./sr-marker";

const NEN = "https://placeholder.invalid";

describe("withSr — gắn marker mà không làm mất chỗ người dùng đang đứng", () => {
  it("GIỮ query nghiệp vụ (có dấu, có ký tự cần encode) và hash", () => {
    // `Nguyễn` cần percent-encode vì phi-ASCII; `:` trong `10:00:00` cũng bị
    // `URLSearchParams` mã hoá lại. Cả hai chỉ được phép ĐỔI CÁCH VIẾT, không
    // được đổi giá trị.
    const target = "/leads?q=Nguyễn&from=2026-06-24T10:00:00#mục-2";

    const ketQua = withSr(target, 1);

    // ── Phép đo 1: giải nghĩa qua `URL` ─────────────────────────────────────
    const url = new URL(ketQua, NEN);
    expect(url.pathname).toBe("/leads");
    expect(url.searchParams.get("q")).toBe("Nguyễn");
    expect(url.searchParams.get("from")).toBe("2026-06-24T10:00:00");
    expect(url.searchParams.get("_sr")).toBe("1");

    // ── Phép đo 2: cắt chuỗi THÔ, không nhờ `URL` phân giải ─────────────────
    expect(ketQua.startsWith("/leads?")).toBe(true);
    const viTriHash = ketQua.indexOf("#");
    expect(viTriHash).toBeGreaterThan(-1);
    expect(decodeURIComponent(ketQua.slice(viTriHash))).toBe("#mục-2");
    const phanQuery = ketQua.slice(ketQua.indexOf("?") + 1, viTriHash);
    expect(decodeURIComponent(phanQuery).split("&")).toEqual([
      "q=Nguyễn",
      "from=2026-06-24T10:00:00",
      "_sr=1",
    ]);
  });

  it("target ĐÃ có `_sr` ⇒ GHI ĐÈ, không nối thêm cái thứ hai", () => {
    // Nối thêm là tự tay dựng ca `_sr` trùng khoá, mà `parseSr` coi ca đó là 0
    // ⇒ bộ đếm về mo và nắp không bao giờ đóng.
    const ketQua = withSr("/admissions/611?_sr=1&tab=ho-so", 2);

    const url = new URL(ketQua, NEN);
    expect(url.searchParams.getAll("_sr")).toEqual(["2"]);
    expect(url.searchParams.get("tab")).toBe("ho-so");
    // Đo thô: chuỗi `_sr=` xuất hiện đúng MỘT lần.
    expect(ketQua.split("_sr=").length - 1).toBe(1);
  });
});

describe("parseSr — đọc marker về phía an toàn", () => {
  it("khoá trùng / không phải số nguyên / âm ⇒ 0, coi như chưa đi vòng nào", () => {
    // Phía an toàn là 0: nắp vẫn đóng ở vòng sau. Tin nhầm một giá trị bịa thì
    // mất nắp, và mất nắp là mất toàn bộ tác dụng của cơ chế.
    expect(parseSr("/x?_sr=1&_sr=2")).toBe(0);
    expect(parseSr("/x?_sr=abc")).toBe(0);
    expect(parseSr("/x?_sr=1.5")).toBe(0);
    expect(parseSr("/x?_sr=-5")).toBe(0);
    expect(parseSr("/x")).toBe(0);
  });

  it("giá trị vượt nắp bị KẸP về `SR_MAX`, không trả nguyên giá trị đọc được", () => {
    // `9` là literal cố ý: nó chạm nắp với MỌI giá trị `SR_MAX`, nên ca này
    // không đổi màu khi ai đó chỉnh nắp — việc canh nắp là của ca đếm vòng.
    expect(parseSr("/x?_sr=9")).toBe(SR_MAX);
    expect(parseSr("/x?_sr=0")).toBe(0);
  });
});

/**
 * ─────────────────────────────────────────────────────────────────────────────
 * Bốn biến dạng của `URLSearchParams` mà ca "giữ query nghiệp vụ" ở trên KHÔNG
 * canh được.
 *
 * `withSr` không chèn chuỗi vào query — nó dựng lại query TỪ ĐẦU qua
 * `URLSearchParams`. Nên nó bảo toàn *giá trị*, chứ không bảo toàn *cách viết*.
 * Đã đo: `?from=2026-06-24T10:00:00` đi ra thành `T10%3A00%3A00`. Khác cách
 * viết là chấp nhận được; khác GIÁ TRỊ thì không, vì đó là mất dữ liệu người
 * dùng đang cầm trên tay.
 *
 * Bốn chỗ `URLSearchParams` có quyền viết lại mà ca cũ đi qua lọt:
 *
 *   1. khoảng trắng — `%20` bị viết lại thành `+` (và `+` phải vẫn đọc ra
 *      khoảng trắng, nếu không người dùng mất từ khoá tìm kiếm);
 *   2. dấu cộng — `%2B` (cộng THẬT, ví dụ số điện thoại `+84…`) và `+`
 *      (khoảng trắng) là HAI thứ khác nhau, không được trộn vào nhau;
 *   3. khoá LẶP — `?a=1&a=2` phải còn đủ cả hai, đúng thứ tự;
 *   4. THỨ TỰ — `?z=1&a=2` không được bị sắp xếp lại.
 *
 * Mỗi ca chỉ vi phạm MỘT bất biến, để khi đỏ thì biết đỏ vì gì.
 *
 * ⚠️ Hai phép đo phải ĐỘC LẬP. `docQueryTho` dưới đây cố ý KHÔNG chạm
 * `URL`/`URLSearchParams`: nếu cả hai phép đo cùng đi qua `URL` thì một lỗi
 * nằm TRONG `URL` sẽ làm hai phép sai theo cùng một kiểu và không phép nào
 * thấy gì.
 */

/**
 * Phân giải query bằng CẮT CHUỖI THÔ — không dùng `URL`/`URLSearchParams`.
 *
 * Thứ tự hai bước giải mã là phần tinh tế nhất: `+` phải thành khoảng trắng
 * TRƯỚC `decodeURIComponent`. Làm ngược lại thì `%2B` vừa giải mã ra `+` sẽ bị
 * bước sau hiểu nhầm là khoảng trắng — tức là chính cái lỗi mà ca số 2 đang đi
 * tìm, nằm ngay bên trong thước đo.
 */
function docQueryTho(target: string): Array<[string, string]> {
  const viTriHash = target.indexOf("#");
  const truocHash = viTriHash === -1 ? target : target.slice(0, viTriHash);
  const viTriHoi = truocHash.indexOf("?");
  if (viTriHoi === -1) return [];
  const chuoiQuery = truocHash.slice(viTriHoi + 1);
  if (chuoiQuery === "") return [];

  const giaiMa = (s: string) => decodeURIComponent(s.replace(/\+/g, " "));

  return chuoiQuery.split("&").map((cap) => {
    const viTriBang = cap.indexOf("=");
    const khoa = viTriBang === -1 ? cap : cap.slice(0, viTriBang);
    const giaTri = viTriBang === -1 ? "" : cap.slice(viTriBang + 1);
    return [giaiMa(khoa), giaiMa(giaTri)] as [string, string];
  });
}

/** Đọc query qua `URL` — phép đo thứ hai, độc lập với `docQueryTho`. */
function docQueryUrl(target: string): Array<[string, string]> {
  return [...new URL(target, NEN).searchParams.entries()];
}

describe("withSr — bốn biến dạng của URLSearchParams không được đổi GIÁ TRỊ", () => {
  it("khoảng trắng: `%20` bị viết lại thành `+`, nhưng vẫn đọc ra khoảng trắng", () => {
    // Bất biến DUY NHẤT của ca này: khoảng trắng trong giá trị sống sót.
    // Ô tìm kiếm `?q=Nguyễn Văn A` là đường thật — mất khoảng trắng thì thành
    // `NguyễnVănA` và không khớp gì cả.
    const target = "/leads?q=Nguy%E1%BB%85n%20V%C4%83n%20A";

    const ketQua = withSr(target, 1);

    // ── Phép đo 1: qua `URL` ────────────────────────────────────────────────
    expect(docQueryUrl(ketQua)).toEqual([
      ["q", "Nguyễn Văn A"],
      ["_sr", "1"],
    ]);

    // ── Phép đo 2: cắt chuỗi thô ────────────────────────────────────────────
    expect(docQueryTho(ketQua)).toEqual([
      ["q", "Nguyễn Văn A"],
      ["_sr", "1"],
    ]);

    // Và ghi lại CÁCH VIẾT thật sự đi ra, để lần sau ai đọc ca này khỏi phải
    // đoán: `%20` ĐÃ thành `+`. Đây là khẳng định về serialization, không phải
    // về giá trị — nó ở đây để biến dạng được NHÌN THẤY, không để canh gác.
    expect(ketQua).toContain("q=Nguy%E1%BB%85n+V%C4%83n+A");
  });

  it("dấu cộng: `%2B` (cộng THẬT) và `+` (khoảng trắng) KHÔNG bị trộn vào nhau", () => {
    // Bất biến DUY NHẤT: hai cách viết vẫn giải mã ra hai giá trị KHÁC nhau
    // sau trọn vòng `withSr` → `stripSr`.
    //
    // `+84901234567` viết đúng trong query là `%2B84…`. Một dấu `+` trần trong
    // query ĐÃ có nghĩa là khoảng trắng theo `application/x-www-form-urlencoded`
    // — trước khi `withSr` kịp chạm vào. Nên ca này không hỏi "dấu cộng trần có
    // còn là dấu cộng không" (nó không, và đó không phải việc của `withSr`);
    // nó hỏi: `withSr` có làm HAI thứ đó lẫn vào nhau không.
    const target = "/leads?sdt=%2B84901234567&bieu_thuc=a+b";
    const truoc: Array<[string, string]> = [
      ["sdt", "+84901234567"],
      ["bieu_thuc", "a b"],
    ];

    // Trọn vòng: gắn marker rồi gỡ marker.
    const khuHoi = stripSr(withSr(target, 2));

    // ── Phép đo 1: qua `URL` ────────────────────────────────────────────────
    expect(docQueryUrl(khuHoi)).toEqual(truoc);

    // ── Phép đo 2: cắt chuỗi thô ────────────────────────────────────────────
    expect(docQueryTho(khuHoi)).toEqual(truoc);

    // Hai giá trị phải KHÁC nhau. Nếu `%2B` bị hạ xuống thành `+` thì cả hai
    // cùng đọc ra khoảng trắng — và phép `toEqual` ở trên vẫn qua được nếu ai
    // đó "sửa cho khớp" biến `truoc`. Khẳng định dưới đây thì không sửa cho
    // khớp được mà vẫn giữ được nghĩa.
    const [sdt, bieuThuc] = docQueryTho(khuHoi);
    expect(sdt[1]).not.toBe(bieuThuc[1]);
    expect(sdt[1].startsWith("+")).toBe(true);
    expect(bieuThuc[1]).toBe("a b");
  });

  it("khoá query LẶP: `?a=1&a=2` giữ ĐỦ cả hai giá trị, không gộp thành một", () => {
    // Bất biến DUY NHẤT: SỐ LƯỢNG giá trị của một khoá lặp không giảm.
    // Bộ lọc nhiều trạng thái (`?trang_thai=submitted&trang_thai=approved`) là
    // đường thật trong danh sách hồ sơ — gộp còn một là người dùng mất nửa bộ
    // lọc sau mỗi lần cứu phiên, mà màn hình vẫn vẽ như bình thường.
    const target =
      "/admissions?trang_thai=submitted&trang_thai=approved&page=3";

    const ketQua = withSr(target, 1);

    // ── Phép đo 1: qua `URL` ────────────────────────────────────────────────
    expect(
      docQueryUrl(ketQua)
        .filter(([khoa]) => khoa === "trang_thai")
        .map(([, giaTri]) => giaTri),
    ).toHaveLength(2);

    // ── Phép đo 2: cắt chuỗi thô ────────────────────────────────────────────
    expect(
      docQueryTho(ketQua)
        .filter(([khoa]) => khoa === "trang_thai")
        .map(([, giaTri]) => giaTri),
    ).toHaveLength(2);
  });

  it("khoá query LẶP: giữ ĐÚNG THỨ TỰ giữa các giá trị cùng khoá", () => {
    // Bất biến DUY NHẤT: thứ tự TƯƠNG ĐỐI của hai giá trị cùng khoá.
    // Tách khỏi ca đếm ở trên có chủ đích: một đột biến đảo thứ tự làm ca này
    // đỏ mà ca đếm vẫn xanh, nên khi đỏ thì biết ngay đỏ vì gì.
    const target =
      "/admissions?trang_thai=submitted&trang_thai=approved&page=3";

    const ketQua = withSr(target, 1);

    // ── Phép đo 1: qua `URL` ────────────────────────────────────────────────
    expect(
      docQueryUrl(ketQua)
        .filter(([khoa]) => khoa === "trang_thai")
        .map(([, giaTri]) => giaTri),
    ).toEqual(["submitted", "approved"]);

    // ── Phép đo 2: cắt chuỗi thô ────────────────────────────────────────────
    expect(
      docQueryTho(ketQua)
        .filter(([khoa]) => khoa === "trang_thai")
        .map(([, giaTri]) => giaTri),
    ).toEqual(["submitted", "approved"]);
  });

  it("THỨ TỰ tham số: `?z=1&a=2` không bị sắp xếp lại theo bảng chữ cái", () => {
    // Bất biến DUY NHẤT: thứ tự các khoá KHÁC nhau giữ nguyên như người dùng
    // đang cầm. `URLSearchParams` có sẵn `sort()`; chỉ cần ai đó gọi nó "cho
    // gọn" là mọi URL người dùng đã bookmark đổi hình sau một lần cứu phiên.
    const target = "/reports?zulu=1&alpha=2&mike=3";

    const ketQua = withSr(target, 1);

    // ── Phép đo 1: qua `URL` ────────────────────────────────────────────────
    expect(docQueryUrl(ketQua).map(([khoa]) => khoa)).toEqual([
      "zulu",
      "alpha",
      "mike",
      "_sr",
    ]);

    // ── Phép đo 2: cắt chuỗi thô ────────────────────────────────────────────
    expect(docQueryTho(ketQua).map(([khoa]) => khoa)).toEqual([
      "zulu",
      "alpha",
      "mike",
      "_sr",
    ]);
  });
});
