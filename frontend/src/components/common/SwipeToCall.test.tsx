import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { SwipeToCall } from "./SwipeToCall";

// jsdom: PointerEvent gốc không giữ clientX/Y ổn định qua fireEvent → thay bằng
// lớp gốc MouseEvent (chắc chắn mang toạ độ). setPointerCapture cũng chưa có.
class TestPointerEvent extends MouseEvent {
  pointerId: number;
  pointerType: string;
  constructor(type: string, params: PointerEventInit = {}) {
    super(type, params);
    this.pointerId = params.pointerId ?? 1;
    this.pointerType = params.pointerType ?? "touch";
  }
}
(globalThis as unknown as { PointerEvent: unknown }).PointerEvent = TestPointerEvent;
if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
if (!Element.prototype.releasePointerCapture) Element.prototype.releasePointerCapture = () => {};

// jsdom: offsetWidth=0 → SwipeToCall fallback 320 → ngưỡng = 320*0.45 = 144px.

function renderSwipe(
  overrides: Partial<React.ComponentProps<typeof SwipeToCall>> = {}
) {
  const onCall = vi.fn();
  const onClick = vi.fn();
  const utils = render(
    <SwipeToCall phone="0900000000" label="Nguyễn Văn A" onCall={onCall} {...overrides}>
      <button onClick={onClick}>card</button>
    </SwipeToCall>
  );
  const root = utils.container.firstChild as HTMLElement;
  return { ...utils, root, onCall, onClick };
}

const down = (el: HTMLElement, x = 0, y = 0) =>
  fireEvent.pointerDown(el, { clientX: x, clientY: y, pointerId: 1, button: 0, pointerType: "touch" });
const move = (el: HTMLElement, x: number, y = 0) =>
  fireEvent.pointerMove(el, { clientX: x, clientY: y, pointerId: 1, pointerType: "touch" });
const up = (el: HTMLElement) =>
  fireEvent.pointerUp(el, { pointerId: 1, pointerType: "touch" });

describe("SwipeToCall — bấm giữ rồi kéo phải để gọi", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("long-press 400ms → kéo qua ngưỡng → thả = gọi", () => {
    const { root, onCall } = renderSwipe();
    down(root, 0, 0);
    vi.advanceTimersByTime(400); // ARM
    move(root, 200, 0); // kéo phải > 144px
    up(root);
    expect(onCall).toHaveBeenCalledWith("0900000000");
  });

  it("đã arm nhưng kéo CHƯA qua ngưỡng → KHÔNG gọi", () => {
    const { root, onCall } = renderSwipe();
    down(root, 0, 0);
    vi.advanceTimersByTime(400);
    move(root, 50, 0); // < 144px
    up(root);
    expect(onCall).not.toHaveBeenCalled();
  });

  it("tap nhanh (chưa đủ 400ms) → KHÔNG gọi, click mở chi tiết vẫn chạy", () => {
    const { root, onCall, onClick, getByText } = renderSwipe();
    down(root, 0, 0);
    vi.advanceTimersByTime(150);
    up(root); // nhả trước khi arm
    fireEvent.click(getByText("card"));
    expect(onCall).not.toHaveBeenCalled();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("di chuyển sớm (cuộn dọc) trước khi arm → KHÔNG arm, KHÔNG gọi", () => {
    const { root, onCall } = renderSwipe();
    down(root, 0, 0);
    move(root, 0, 40); // cuộn dọc 40px → huỷ arm-timer
    vi.advanceTimersByTime(400);
    move(root, 200, 40);
    up(root);
    expect(onCall).not.toHaveBeenCalled();
  });

  it("sau long-press+kéo, click kế tiếp bị chặn (không mở chi tiết oan)", () => {
    const { root, onCall, onClick, getByText } = renderSwipe();
    down(root, 0, 0);
    vi.advanceTimersByTime(400);
    move(root, 200, 0);
    up(root);
    fireEvent.click(getByText("card")); // trình duyệt có thể phát click sau drag
    expect(onCall).toHaveBeenCalledTimes(1);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("gesture bị huỷ giữa chừng (pointercancel) → KHÔNG nuốt oan tap kế tiếp", () => {
    const { root, onCall, onClick, getByText } = renderSwipe();
    // Gesture 1: long-press (arm) rồi huỷ.
    down(root, 0, 0);
    vi.advanceTimersByTime(400);
    fireEvent.pointerCancel(root, { pointerId: 1, pointerType: "touch" });
    // Gesture 2: tap nhanh → phải mở chi tiết (click không bị chặn oan).
    down(root, 0, 0);
    vi.advanceTimersByTime(120);
    up(root);
    fireEvent.click(getByText("card"));
    expect(onCall).not.toHaveBeenCalled();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("bấm-giữ trên control [data-swipe-ignore] (menu ⋮ / checkbox) → KHÔNG arm, click con vẫn chạy", () => {
    // Regression: trước đây long-press ≥400ms trên nút con vẫn arm gesture rồi
    // onClickCapture nuốt tap → menu không mở / checkbox không tick.
    const onCall = vi.fn();
    const onChild = vi.fn();
    const utils = render(
      <SwipeToCall phone="0900000000" onCall={onCall}>
        <button data-swipe-ignore onClick={onChild}>
          menu
        </button>
      </SwipeToCall>
    );
    const child = utils.getByText("menu");
    down(child, 0, 0);
    vi.advanceTimersByTime(400); // vượt ARM_MS mà KHÔNG được khoá chế độ kéo
    up(child);
    fireEvent.click(child);
    expect(onCall).not.toHaveBeenCalled();
    expect(onChild).toHaveBeenCalledTimes(1);
  });

  it("không có SĐT → render children, bỏ qua cử chỉ", () => {
    const onCall = vi.fn();
    const { getByText, root } = (() => {
      const utils = render(
        <SwipeToCall phone={null} onCall={onCall}>
          <button>no-phone</button>
        </SwipeToCall>
      );
      return { ...utils, root: utils.container.firstChild as HTMLElement };
    })();
    expect(getByText("no-phone")).toBeInTheDocument();
    down(root, 0, 0);
    vi.advanceTimersByTime(400);
    move(root, 200, 0);
    up(root);
    expect(onCall).not.toHaveBeenCalled();
  });
});
