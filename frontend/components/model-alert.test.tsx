// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError, createApiError } from "@/lib/api";

import { ModelAlert, modelAlertCode } from "./model-alert";

describe("ModelAlert", () => {
  it("links to the model settings", () => {
    render(<ModelAlert code="model_not_set" message="No chat model is set." />);

    expect(screen.getByRole("alert")).toHaveTextContent("No chat model chosen");
    expect(screen.getByRole("link", { name: "Go to model settings" })).toHaveAttribute(
      "href",
      "/settings#models",
    );
  });

  it("shows the backend message naming the model", () => {
    render(<ModelAlert code="model_unavailable" message="The model 'org/m' is not available." />);

    expect(screen.getByRole("alert")).toHaveTextContent("org/m");
  });

  it.each(["model_not_set", "model_unknown", "model_unsupported", "model_unavailable"])(
    "maps %s to its alert code",
    (code) => {
      expect(modelAlertCode(createApiError(code, "", 409))).toBe(code);
    },
  );

  it("ignores other errors", () => {
    expect(modelAlertCode(new ApiError("not_found", "", 404))).toBeNull();
  });
});
