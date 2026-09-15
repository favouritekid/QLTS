import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Ignore test files
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/__tests__/**",
  ]),

  // ---------------------------------------------------------------------------
  // Hai script harness CommonJS — allowlist ĐÚNG TỪNG MODULE, không tắt rule
  // ---------------------------------------------------------------------------
  //
  // `totp-coordinator.js` và `totp-reserve-cli.js` CỐ Ý là CommonJS `.js`: ca
  // kiểm ngược "hai tiến trình không lấy cùng counter" chạy trong shard pytest
  // (Tier 5) bằng `node` TRẦN — ở đó không có `frontend/node_modules`, không có
  // `tsc`, không có bundler. Đổi sang ESM hay `.mjs`/`.cjs`/`.ts` là phá đúng
  // tính chất khiến ca kiểm ấy chạy được, tức biến một bất biến đã ĐO thành
  // "đọc mã rồi tin".
  //
  // Vì vậy rule `no-require-imports` được giữ ở mức `error`, chỉ nới bằng
  // `allow` neo hai đầu (`^…$`) cho ĐÚNG những module hai tệp đang dùng. Một
  // `require()` MỚI — kể cả `node:http`, kể cả một đường dẫn tương đối khác —
  // vẫn ĐỎ. Không dùng `node:.*` hay `\./.*`: mẫu rộng sẽ biến cổng này thành
  // vô hiệu mà không ai nhận ra.
  {
    files: ["src/test/e2e/helpers/totp-coordinator.js"],
    languageOptions: { sourceType: "commonjs" },
    rules: {
      "@typescript-eslint/no-require-imports": [
        "error",
        { allow: ["^node:crypto$", "^node:fs$", "^node:os$", "^node:path$"] },
      ],
    },
  },
  {
    files: ["src/test/e2e/helpers/totp-reserve-cli.js"],
    languageOptions: { sourceType: "commonjs" },
    rules: {
      "@typescript-eslint/no-require-imports": [
        "error",
        { allow: ["^node:crypto$", "^\\./totp-coordinator$"] },
      ],
    },
  },
]);

export default eslintConfig;
