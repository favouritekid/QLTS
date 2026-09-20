/**
 * Nắp chống lặp của vòng cứu phiên, nhìn từ phía proxy.
 *
 * Tách khỏi `proxy.matrix.test.ts` vì ở đây nắp được chạy như một VÒNG LẶP
 * nhiều lượt, không phải một request đơn lẻ: một ca một-lượt vẫn xanh ngay cả
 * khi nắp bị gỡ sạch, vì lượt đầu tiên vốn dĩ không chạm nắp.
 *
 * Bước "bootstrap ghi marker rồi quay về target" được gọi thẳng vào
 * `lib/auth/sr-marker` — đúng module mà `SessionRefreshBootstrap.tsx` dùng.
 * Chép lại hai dòng ấy vào đây thì ca chỉ còn kiểm chính nó.
 */
import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";

import { proxy } from "./proxy";
import { parseSr, withSr } from "@/lib/auth/sr-marker";

const BASE = "https://qlts.tnpc.edu.vn";

function trangCuuPhien(target: string): NextRequest {
  return new NextRequest(
    new URL(`/session-refresh?redirect=${encodeURIComponent(target)}`, BASE),
  );
}

function locationOf(res: Response): string {
  return decodeURIComponent(res.headers.get("location") ?? "");
}

describe("nắp `_sr` — vòng cứu phiên phải DỪNG", () => {
  it("chạy 6 lượt: bootstrap chỉ được render ĐÚNG 2 lượt rồi proxy chặn về /login", async () => {
    let target = "/admissions/611";
    let soLuotRender = 0;
    let soLanDungLai = 0;

    for (let i = 0; i < 6; i++) {
      const res = await proxy(trangCuuPhien(target));

      if (res.status === 200) {
        // Proxy cho trang bootstrap render. Làm mới xong, bootstrap quay về
        // target KÈM marker — đúng hai lời gọi dưới đây, vào module thật.
        soLuotRender++;
        target = withSr(target, parseSr(target) + 1);
        continue;
      }

      expect(res.status).toBe(307);
      const loc = locationOf(res);
      expect(loc).toContain("/login");
      expect(loc).toContain("reauth=true");
      soLanDungLai++;
      break;
    }

    // Literal `2`, KHÔNG viết `SR_MAX`: lấy hằng làm kỳ vọng thì đổi hằng cũng
    // tự sửa luôn kỳ vọng, và con số này hết được canh.
    expect(soLuotRender).toBe(2);
    expect(soLanDungLai).toBe(1);
  });

  it("`_sr=9` (vượt nắp) ⇒ chặn NGAY lượt đầu, không cho bootstrap render", async () => {
    const res = await proxy(trangCuuPhien("/admissions/611?_sr=9"));

    expect(res.status).toBe(307);
    const loc = locationOf(res);
    expect(loc).toContain("/login");
    expect(loc).toContain("reauth=true");
  });

  it("chạm nắp ⇒ `/login` KHÔNG mang `_sr`, nhưng GIỮ return-url", async () => {
    // Mang `_sr` sang `/login` nghĩa là đăng nhập lại xong người dùng đáp
    // xuống `X?_sr=2`, và chu kỳ sau đóng nắp ngay từ vòng đầu.
    const res = await proxy(trangCuuPhien("/admissions/611?tab=ho-so&_sr=9"));

    const loc = locationOf(res);
    expect(loc).not.toContain("_sr");
    expect(loc).toContain("redirect=/admissions/611?tab=ho-so");
  });

  it("`_sr=1` (còn dưới nắp) ⇒ vẫn cho bootstrap render — nắp không được đóng sớm", async () => {
    const res = await proxy(trangCuuPhien("/admissions/611?_sr=1"));

    expect(res.status).toBe(200);
  });
});
