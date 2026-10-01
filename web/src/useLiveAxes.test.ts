import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { Robot } from "./types";

const { cmdDirectMode } = vi.hoisted(() => ({ cmdDirectMode: vi.fn(() => Promise.resolve({ ok: true, direct: true })) }));
vi.mock("./commands", () => ({ cmdDirectMode }));

import { useLiveAxes } from "./useLiveAxes";

const robotOn: Robot = {
  id: "robot_1", is_master: true, connected: true, port: "USB0",
  torque_enabled: true, state: "READY",
  smooth_hz: 50, comfort_vel: 100, comfort_acc: 20,
  soft_limits: { "3": [1000, 3000] },
};
const noop = () => {};

beforeEach(() => { cmdDirectMode.mockClear(); });

describe("useLiveAxes", () => {
  it("value() reflète la position live du robot", () => {
    const { result } = renderHook(() =>
      useLiveAxes({ rid: "robot_1", robot: robotOn,
        hw: { "1": 1500, "2": 2000 }, direct: false, wsSend: vi.fn(), onError: noop }));
    expect(result.current.value(1)).toBe(1500);
    expect(result.current.value(2)).toBe(2000);
  });

  it("value() retombe sur 2048 pour un axe inconnu", () => {
    const { result } = renderHook(() =>
      useLiveAxes({ rid: "robot_1", robot: robotOn,
        hw: {}, direct: false, wsSend: vi.fn(), onError: noop }));
    expect(result.current.value(5)).toBe(2048);
  });

  it("onChange en Direct envoie jog.intent", () => {
    const wsSend = vi.fn();
    const { result } = renderHook(() => useLiveAxes({
      rid: "robot_1", robot: robotOn, hw: { "5": 1000 },
      direct: true, wsSend, onError: noop }));
    act(() => { result.current.onChange(5, 2000); });
    expect(wsSend).toHaveBeenCalledWith({ type: "jog.intent", rid: "robot_1", axis: 5, target: 2000 });
  });

  it("le drag envoie un heartbeat jog.alive (10 Hz)", () => {
    vi.useFakeTimers();
    const wsSend = vi.fn();
    const { result } = renderHook(() => useLiveAxes({
      rid: "robot_1", robot: robotOn, hw: { "5": 1000 },
      direct: true, wsSend, onError: noop }));
    act(() => { result.current.onPointerDown(5); });
    act(() => { vi.advanceTimersByTime(250); });
    const alive = wsSend.mock.calls.filter((c) => (c[0] as { type: string }).type === "jog.alive");
    expect(alive.length).toBeGreaterThanOrEqual(2);
    act(() => { result.current.onPointerUp(5); });
    wsSend.mockClear();
    act(() => { vi.advanceTimersByTime(250); });
    expect(wsSend).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("le toggle Direct appelle cmdDirectMode", () => {
    const wsSend = vi.fn();
    const { rerender, unmount } = renderHook(
      ({ direct }) => useLiveAxes({
        rid: "robot_1", robot: robotOn, hw: { "5": 1000 },
        direct, wsSend, onError: noop }),
      { initialProps: { direct: false } });
    rerender({ direct: true });
    expect(cmdDirectMode).toHaveBeenCalledWith("robot_1", true);
    unmount();
    expect(cmdDirectMode).toHaveBeenCalledWith("robot_1", false);
  });
});
