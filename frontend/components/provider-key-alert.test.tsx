// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError, ProviderKeyMissingError, ProviderKeyRejectedError } from "@/lib/api";

import { ProviderKeyAlert, providerKeyAlertCode } from "./provider-key-alert";

describe("ProviderKeyAlert", () => {
  it("shows the missing-key message naming the provider, with a link to settings", () => {
    render(
      <ProviderKeyAlert
        code="provider_key_missing"
        message="Add your NVIDIA API key in settings to use this feature."
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("No API key saved");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Add your NVIDIA API key in settings to use this feature.",
    );
    expect(
      screen.getByRole("link", { name: "Go to provider settings" }),
    ).toHaveAttribute("href", "/settings");
  });

  it("shows the rejected-key message naming the provider", () => {
    render(
      <ProviderKeyAlert
        code="provider_key_rejected"
        message="Your saved OpenRouter API key no longer works. Update it in settings."
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Your API key no longer works");
    expect(screen.getByRole("alert")).toHaveTextContent("OpenRouter");
  });

  it("maps API errors to alert codes", () => {
    expect(
      providerKeyAlertCode(new ProviderKeyMissingError("provider_key_missing", "", 409)),
    ).toBe("provider_key_missing");
    expect(
      providerKeyAlertCode(new ProviderKeyRejectedError("provider_key_rejected", "", 409)),
    ).toBe("provider_key_rejected");
    expect(providerKeyAlertCode(new ApiError("not_found", "", 404))).toBeNull();
  });
});
