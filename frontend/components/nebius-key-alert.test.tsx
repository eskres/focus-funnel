// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ApiError,
  NebiusKeyMissingError,
  NebiusKeyRejectedError,
} from "@/lib/api";

import { NebiusKeyAlert, nebiusKeyAlertCode } from "./nebius-key-alert";

describe("NebiusKeyAlert", () => {
  it("shows the missing-key message with a link to settings", () => {
    render(<NebiusKeyAlert code="nebius_key_missing" />);

    expect(screen.getByRole("alert")).toHaveTextContent("No Nebius API key saved");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This feature needs your Nebius API key.",
    );
    expect(
      screen.getByRole("link", { name: "Go to API key settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("shows the rejected-key message with a link to settings", () => {
    render(<NebiusKeyAlert code="nebius_key_rejected" />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Your Nebius API key no longer works",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Nebius rejected your saved API key.",
    );
    expect(
      screen.getByRole("link", { name: "Go to API key settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("maps API errors to alert codes", () => {
    expect(
      nebiusKeyAlertCode(new NebiusKeyMissingError("nebius_key_missing", "", 400)),
    ).toBe("nebius_key_missing");
    expect(
      nebiusKeyAlertCode(new NebiusKeyRejectedError("nebius_key_rejected", "", 400)),
    ).toBe("nebius_key_rejected");
    expect(nebiusKeyAlertCode(new ApiError("not_found", "", 404))).toBeNull();
  });
});
