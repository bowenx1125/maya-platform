import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useFileDrop } from "../components/ui/use-file-drop";

afterEach(cleanup);

function Tile(props: Parameters<typeof useFileDrop>[0]) {
  const drop = useFileDrop(props);
  return (
    <label data-testid="tile" {...drop}>
      <span>Disc</span>
      <input type="file" />
    </label>
  );
}

describe("useFileDrop", () => {
  it("ignores non-file drags and empty drops, and hands off only the first file", () => {
    const onFile = vi.fn();
    render(<Tile onFile={onFile} />);
    const tile = screen.getByTestId("tile");
    const text = { types: ["text/plain"], files: [] };
    expect(fireEvent.dragEnter(tile, { dataTransfer: text })).toBe(true);
    expect(fireEvent.dragOver(tile, { dataTransfer: text })).toBe(true);
    expect(fireEvent.drop(tile, { dataTransfer: text })).toBe(true);
    expect(tile.hasAttribute("data-drag")).toBe(false);
    expect(
      fireEvent.drop(tile, { dataTransfer: { types: ["Files"], files: [] } }),
    ).toBe(false);
    expect(onFile).not.toHaveBeenCalled();
    const first = new File(["one"], "one.md");
    fireEvent.drop(tile, {
      dataTransfer: {
        types: ["Files"],
        files: [first, new File(["two"], "two.md")],
      },
    });
    expect(onFile).toHaveBeenCalledExactlyOnceWith(first);
  });

  it.each([{ disabled: true }, { busy: true }])(
    "prevents navigation while blocked (%j)",
    (blocked) => {
      const onFile = vi.fn();
      const view = render(<Tile onFile={onFile} />);
      const tile = screen.getByTestId("tile");
      const dataTransfer = {
        types: ["Files"],
        files: [new File(["one"], "one.md")],
        dropEffect: "copy",
      };
      fireEvent.dragEnter(tile, { dataTransfer });
      expect(tile.getAttribute("data-drag")).toBe("over");
      view.rerender(<Tile onFile={onFile} {...blocked} />);
      expect(tile.hasAttribute("data-drag")).toBe(false);
      expect(fireEvent.dragOver(tile, { dataTransfer })).toBe(false);
      expect(fireEvent.drop(tile, { dataTransfer })).toBe(false);
      expect(onFile).not.toHaveBeenCalled();
      expect(dataTransfer.dropEffect).toBe("none");
    },
  );
});
