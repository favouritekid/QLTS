/**
 * Backend GIẢ cho phép đo render của ảnh frontend (frontend-image-smoke.yml).
 *
 * Chỉ trả hai đường mà `/dashboard` gọi phía server:
 *   GET /api/users/me               → người dùng role admin, để trang KHÔNG
 *                                     redirect sang /dashboard/officer
 *   GET /api/admin/users/statistics → số liệu mang giá trị DẤU (total_users 731),
 *                                     đi qua getCachedUserStatistics ('use cache')
 * Đường kiểm ngược: token có `jti` chứa "kiem-nguoc" ⇒ statistics trả 500, nên
 * dấu PHẢI biến mất khỏi trang của đúng token đó.
 * GET /healthz → 200, không ghi log. Mọi đường khác: 404.
 *
 * Mỗi request (trừ /healthz) ghi một dòng JSON: thời điểm, method, path và `jti`
 * đọc từ cookie access_token. Token là token GIẢ do frontend-smoke-check.sh tự
 * tạo (không chữ ký); KHÔNG ghi giá trị cookie.
 *
 * CLI: node frontend-smoke-backend.js <port> <log.jsonl>
 */

'use strict';

const fs = require('fs');
const http = require('http');

const [port, logPath] = process.argv.slice(2);

if (!port || !logPath) {
  console.error('Usage: node frontend-smoke-backend.js <port> <log.jsonl>');
  process.exit(2);
}

const STATS = {
  total_users: 731,
  active_users: 613,
  pending_users: 47,
  banned_users: 5,
  new_users_last_7_days: 29,
  new_users_last_30_days: 88,
  users_by_role: { admin: 3, manager: 7, officer: 41 },
  recent_activities: [],
};

const ME = {
  id: 1,
  email: 'smoke@example.invalid',
  full_name: 'Frontend Smoke',
  role: 'admin',
  is_active: true,
  is_verified: true,
  unit_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function jtiOf(cookieHeader) {
  const m = /(?:^|;\s*)access_token=([^;]+)/.exec(cookieHeader || '');
  if (!m) return null;
  try {
    const payload = JSON.parse(
      Buffer.from(m[1].split('.')[1] || '', 'base64url').toString('utf8'),
    );
    return typeof payload.jti === 'string' ? payload.jti : '<khong-co-jti>';
  } catch {
    return '<khong-giai-ma-duoc>';
  }
}

http
  .createServer((req, res) => {
    const path = req.url.split('?')[0];
    const send = (code, obj) => {
      res.writeHead(code, { 'content-type': 'application/json' });
      res.end(JSON.stringify(obj));
    };
    if (path === '/healthz') return send(200, { ok: true });

    const jti = jtiOf(req.headers.cookie);
    fs.appendFileSync(
      logPath,
      JSON.stringify({ t: new Date().toISOString(), m: req.method, path, jti }) + '\n',
    );

    if (req.method === 'GET' && path === '/api/users/me') return send(200, ME);
    if (req.method === 'GET' && path === '/api/admin/users/statistics') {
      if (jti && jti.includes('kiem-nguoc')) {
        return send(500, { detail: 'loi gia cho kiem nguoc' });
      }
      return send(200, STATS);
    }
    return send(404, { detail: 'Not Found' });
  })
  .listen(Number(port), '127.0.0.1', () => {
    console.log('frontend-smoke-backend nghe 127.0.0.1:' + port);
  });
