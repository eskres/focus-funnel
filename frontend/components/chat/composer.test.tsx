// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Composer } from "./composer";

afterEach(() => {
  vi.clearAllMocks();
});

describe("Composer", () => {
  it("shows Stop and no Send while an answer arrives with onStop", () => {
    render(<Composer disabled onSend={vi.fn()} onStop={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
  });

  it("calls onStop once when Stop is pressed", () => {
    const onStop = vi.fn();
    const onSend = vi.fn();
    render(<Composer disabled onSend={onSend} onStop={onStop} />);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows Stopping… and disables it while stopping", () => {
    const onStop = vi.fn();
    render(<Composer disabled onSend={vi.fn()} onStop={onStop} stopping />);

    const button = screen.getByRole("button", { name: "Stopping…" });
    expect(button).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(onStop).not.toHaveBeenCalled();
  });

  it("keeps Stop disabled until the answer can be stopped", () => {
    render(<Composer disabled onSend={vi.fn()} onStop={vi.fn()} canStop={false} />);

    expect(screen.getByRole("button", { name: "Stop" })).toBeDisabled();
  });

  it("shows a disabled Send, as before, when disabled without onStop", () => {
    render(<Composer disabled onSend={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Stop/ })).not.toBeInTheDocument();
  });

  it("shows Send, not Stop, when enabled even with onStop", () => {
    render(<Composer disabled={false} onSend={vi.fn()} onStop={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
  });

  it("does not stop the answer on Enter in the input", () => {
    const onStop = vi.fn();
    const onSend = vi.fn();
    render(<Composer disabled onSend={onSend} onStop={onStop} />);
    const input = screen.getByLabelText("Message");

    fireEvent.change(input, { target: { value: "hello" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.submit(input.closest("form")!);

    expect(onStop).not.toHaveBeenCalled();
    expect(onSend).not.toHaveBeenCalled();
  });
});
