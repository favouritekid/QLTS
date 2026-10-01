// @vitest-environment jsdom
/**
 * Inline error of the login form, per server response.
 *
 * Renders the REAL `LoginForm` (real `useAuth`, real axios instance with its
 * interceptors and its XHR adapter). Only the server is replaced, by an MSW
 * handler answering the way the real one does: JSON for the backend, an HTML
 * page for nginx's own 503 (`limit_req` on `/api/auth/login` has no
 * `limit_req_status`, so it answers 503 with no `error_code`).
 *
 * Only a backend 503 with exactly `AUTH_STATE_UNAVAILABLE` gets the new
 * message; every other 503/500 keeps the generic one; 429/401 are unchanged.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

// Only the ROUTER infrastructure is mocked (jsdom has no app router).
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/login",
}));

import { server } from "@/test/mocks/server";
import { setApiLoggedOut } from "@/lib/api/session-flags";
import {
  installFakeIdb,
  removeWebLocks,
} from "@/lib/api/refresh-coordination/test-harness";

import { LoginForm } from "./LoginForm";

const GENERIC_MESSAGE = "Đã xảy ra lỗi. Vui lòng thử lại.";
const AUTH_STATE_MESSAGE =
  "Hệ thống xác thực tạm thời không sẵn sàng. Vui lòng thử lại sau.";
const WRONG_CREDENTIALS_MESSAGE = "Tên đăng nhập hoặc mật khẩu không đúng.";
// Literal, not imported: this is what the backend puts on the wire.
const AUTH_STATE_CODE = "AUTH_STATE_UNAVAILABLE";

const NGINX_503_HTML =
  "<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n" +
  "<body>\r\n<center><h1>503 Service Temporarily Unavailable</h1></center>\r\n" +
  "<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n";

type Reply = () => Response;

function json(status: number, body: unknown, headers: Record<string, string> = {}): Reply {
  return () => HttpResponse.json(body as never, { status, headers });
}

function html(status: number, body: string): Reply {
  return () =>
    new HttpResponse(body, { status, headers: { "Content-Type": "text/html" } });
}

/** Serve `reply` for the login POST, submit the form, return the inline alert. */
async function submitLoginAgainst(reply: Reply): Promise<HTMLElement> {
  const requests: string[] = [];
  server.use(
    http.post("*/api/auth/login", ({ request }) => {
      requests.push(request.url);
      return reply();
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <LoginForm />
    </QueryClientProvider>,
  );

  fireEvent.change(await screen.findByLabelText("Tên đăng nhập"), {
    target: { value: "officer1" },
  });
  // The "Mật khẩu" label points at the wrapper <div> (show/hide button next to
  // the input), not at the input itself.
  const password = document.querySelector<HTMLInputElement>(
    'input[autocomplete="current-password"]',
  );
  if (!password) throw new Error("password input not rendered");
  fireEvent.change(password, { target: { value: "not-the-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

  const alert = await screen.findByRole("alert");
  // The response came from the handler above, not from any other route.
  expect(requests).toHaveLength(1);
  return alert;
}

beforeEach(() => {
  window.localStorage.clear();
  installFakeIdb();
  removeWebLocks();
  setApiLoggedOut(false);
  window.history.replaceState({}, "", "/login");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("LoginForm — backend 503 AUTH_STATE_UNAVAILABLE", () => {
  it("shows the backend's detail (the real body)", async () => {
    const alert = await submitLoginAgainst(
      json(503, { detail: AUTH_STATE_MESSAGE, error_code: AUTH_STATE_CODE }, { "Retry-After": "60" }),
    );

    expect(alert.textContent).toBe(AUTH_STATE_MESSAGE);
  });

  it("shows the backend's detail, whatever its wording", async () => {
    const detail = "Máy chủ xác thực đang bảo trì (probe).";
    const alert = await submitLoginAgainst(
      json(503, { detail, error_code: AUTH_STATE_CODE }, { "Retry-After": "60" }),
    );

    expect(alert.textContent).toBe(detail);
  });

  it("falls back to its own sentence when the body has no detail", async () => {
    const alert = await submitLoginAgainst(json(503, { error_code: AUTH_STATE_CODE }));

    expect(alert.textContent).toBe(AUTH_STATE_MESSAGE);
  });

  it("does not lock the form: Retry-After is a hint, not a countdown", async () => {
    const alert = await submitLoginAgainst(
      json(503, { detail: AUTH_STATE_MESSAGE, error_code: AUTH_STATE_CODE }, { "Retry-After": "60" }),
    );

    expect(alert.textContent).not.toMatch(/khóa/);
    expect((screen.getByRole("button", { name: "Đăng nhập" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByLabelText("Tên đăng nhập") as HTMLInputElement).disabled).toBe(false);
  });
});

describe("LoginForm — every other 5xx keeps the generic message", () => {
  it.each<[string, Reply]>([
    ["nginx 503 (HTML body, no code)", html(503, NGINX_503_HTML)],
    ["503 with an empty JSON body", json(503, {})],
    [
      "503 with another code",
      json(503, { detail: "Dịch vụ tạm thời chưa sẵn sàng.", error_code: "SERVICE_UNAVAILABLE" }),
    ],
    [
      "503 with the code in another case",
      json(503, { detail: AUTH_STATE_MESSAGE, error_code: "auth_state_unavailable" }),
    ],
    [
      "500 carrying the code (the status must be 503)",
      json(500, { detail: AUTH_STATE_MESSAGE, error_code: AUTH_STATE_CODE }),
    ],
    ["500", json(500, { detail: "An internal server error occurred.", error_code: "INTERNAL_ERROR" })],
  ])("%s", async (_name, reply) => {
    const alert = await submitLoginAgainst(reply);

    expect(alert.textContent).toBe(GENERIC_MESSAGE);
  });
});

describe("LoginForm — 429 and 401 unchanged", () => {
  it("429 lockout: countdown message, form locked", async () => {
    const alert = await submitLoginAgainst(
      json(
        429,
        { detail: "Tài khoản tạm thời bị khóa do nhập sai quá nhiều lần. Vui lòng thử lại sau 13 phút." },
        { "Retry-After": "777" },
      ),
    );

    // Retry-After 777 s = 12m 57s; the countdown may already have ticked.
    expect(alert.textContent).toMatch(/^Tài khoản tạm bị khóa\. Thử lại sau 12m 5\ds\.$/);
    expect((screen.getByRole("button", { name: "Đăng nhập" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("401: wrong credentials", async () => {
    const alert = await submitLoginAgainst(
      json(401, { detail: "Incorrect username or password.", error_code: "INVALID_CREDENTIALS" }),
    );

    expect(alert.textContent).toBe(WRONG_CREDENTIALS_MESSAGE);
  });
});
