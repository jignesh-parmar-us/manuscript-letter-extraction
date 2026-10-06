import { render } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { useFitHeight } from "./useFitHeight";

function Side({ top }: { top: number }) {
  const ref = useRef<HTMLElement>(null);
  useFitHeight(ref);
  return (
    <aside
      ref={(el) => {
        if (el) el.getBoundingClientRect = () => ({ top }) as DOMRect;
        (ref as { current: HTMLElement | null }).current = el;
      }}
      data-testid="side"
    />
  );
}

describe("useFitHeight", () => {
  it("ends the side bar at the window's bottom wherever it starts", () => {
    Object.assign(window, { innerWidth: 1400, innerHeight: 900 });
    const { getByTestId, unmount } = render(<Side top={330} />);
    expect(getByTestId("side").style.maxHeight).toBe(`${900 - 330 - 8}px`);
    unmount();
    const stuck = render(<Side top={-50} />);                     // scrolled: it sticks 8 px from the top
    expect(stuck.getByTestId("side").style.maxHeight).toBe(`${900 - 8 - 8}px`);
  });

  it("leaves narrow windows to the style sheet", () => {
    Object.assign(window, { innerWidth: 700, innerHeight: 900 });
    const { getByTestId } = render(<Side top={330} />);
    expect(getByTestId("side").style.maxHeight).toBe("");
  });
});
