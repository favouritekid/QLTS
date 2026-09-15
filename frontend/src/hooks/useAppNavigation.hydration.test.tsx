// @vitest-environment jsdom
/**
 * GUARD (de xuat) — bat bien "lan render client DAU TIEN cua MOI instance
 * useAppNavigation() phai dung dung du lieu server (user chua kha dung)".
 *
 * Cach do: dung `renderToString` voi useAuth().user = null (dieu kien server),
 * roi `hydrateRoot` DUNG chuoi HTML do trong khi useAuth() DA co user officer
 * (dieu kien client co persisted user). Neu hook doc thang persisted user o lan
 * render dau, React se bao recoverable error (hydration mismatch).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as React from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { act } from "react";

// --- useAuth gia lap: doi duoc giua "server" (null) va "client" (officer) ---
const authState: { user: { id: number; username: string; role: string } | null } = { user: null };
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: authState.user }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/admissions" }));

import { useAppNavigation } from "./useAppNavigation";

function NavProbe() {
  const { navigation } = useAppNavigation();
  const hrefs = navigation.flatMap((g) => g.items).map((i) => i.href);
  return (
    <ul>
      {hrefs.map((h) => (
        <li key={h}>
          <a href={h}>{h}</a>
        </li>
      ))}
    </ul>
  );
}

describe("useAppNavigation — lan render client dau tien phai khop server", () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
  });
  afterEach(() => {
    container.remove();
    authState.user = null;
  });

  it("khong sinh hydration mismatch khi client DA co user tu persist", async () => {
    // 1) HTML server: chua biet user
    authState.user = null;
    const serverHtml = renderToString(<NavProbe />);
    container.innerHTML = serverHtml;

    // 2) Client: persisted user da co SAN truoc khi hydrate
    authState.user = { id: 1, username: "vothithuthuhien", role: "officer" };

    const recoverable: string[] = [];
    await act(async () => {
      hydrateRoot(container, <NavProbe />, {
        onRecoverableError: (e) => recoverable.push(String((e as Error)?.message ?? e)),
      });
    });

    expect(recoverable.filter((m) => /[Hh]ydrat/.test(m))).toEqual([]);
  });

  it("instance mount MUON cung phai khop server — co phai THEO TUNG INSTANCE", async () => {
    // HTML server duoc dung MOT LAN (server that khong biet gi ve co phia client).
    authState.user = null;
    const serverHtml = renderToString(<NavProbe />);

    // Cay thu nhat: hydrate binh thuong. Neu co readiness la TOAN CUC thi no
    // bat o day va van con bat khi cay thu hai mount.
    const first = document.createElement("div");
    document.body.appendChild(first);
    first.innerHTML = serverHtml;
    authState.user = { id: 1, username: "vothithuthuhien", role: "officer" };
    await act(async () => {
      hydrateRoot(first, <NavProbe />, { onRecoverableError: () => {} });
    });

    // Cay thu hai: mo phong bien <Suspense> duoc GHEP MUON — cung HTML server.
    const late = document.createElement("div");
    document.body.appendChild(late);
    late.innerHTML = serverHtml;
    const recoverable: string[] = [];
    await act(async () => {
      hydrateRoot(late, <NavProbe />, {
        onRecoverableError: (e) => recoverable.push(String((e as Error)?.message ?? e)),
      });
    });
    first.remove();
    late.remove();

    expect(recoverable.filter((m) => /[Hh]ydrat/.test(m))).toEqual([]);
  });

  it("sau khi mount, navigation phai co muc theo vai tro officer", async () => {
    authState.user = null;
    const serverHtml = renderToString(<NavProbe />);
    container.innerHTML = serverHtml;
    expect(serverHtml).not.toContain("/dashboard/officer");

    authState.user = { id: 1, username: "vothithuthuhien", role: "officer" };
    await act(async () => {
      hydrateRoot(container, <NavProbe />, { onRecoverableError: () => {} });
    });
    expect(container.innerHTML).toContain("/dashboard/officer");
  });
});
