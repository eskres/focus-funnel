// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, fakeApi, json } from "@/test/fake-api";

import { CategoriesSection } from "./categories-settings";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

const FIXED = ["task", "idea", "decision", "note", "reference"];

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function list() {
  return screen.findByRole("list", { name: "Your categories" });
}

function add(name: string) {
  fireEvent.change(screen.getByLabelText("New category"), { target: { value: name } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
}

describe("CategoriesSection", () => {
  it("shows the fixed kinds without a remove button, and the added ones with one", async () => {
    fakeApi({ "GET /api/settings/categories": json(200, { fixed: FIXED, added: ["recipe"] }) });
    render(<CategoriesSection />);

    const items = within(await list()).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([...FIXED, "recipe"]);
    expect(within(await list()).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Remove recipe",
    ]);
  });

  it("adds a category and shows it as the server cleaned it", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/categories": json(200, { fixed: FIXED, added: [] }),
      "POST /api/settings/categories": json(201, { fixed: FIXED, added: ["recipe"] }),
    });
    render(<CategoriesSection />);
    await list();

    add(" Recipe");

    expect(await within(await list()).findByText("recipe")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: " Recipe" });
    expect(screen.getByLabelText("New category")).toHaveValue("");
  });

  it("shows the server's message for a duplicate and keeps the text", async () => {
    fakeApi({
      "GET /api/settings/categories": json(200, { fixed: FIXED, added: [] }),
      "POST /api/settings/categories": errorResponse(409, "category_exists", "The category 'idea' exists already."),
    });
    render(<CategoriesSection />);
    await list();

    add("Idea");

    expect(await screen.findByRole("alert")).toHaveTextContent("The category 'idea' exists already.");
    expect(screen.getByLabelText("New category")).toHaveValue("Idea");
  });

  it("removes an added category from the list", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/categories": json(200, { fixed: FIXED, added: ["recipe", "travel"] }),
      "DELETE /api/settings/categories/recipe": new Response(null, { status: 204 }),
    });
    render(<CategoriesSection />);

    fireEvent.click(within(await list()).getByRole("button", { name: "Remove recipe" }));

    await waitFor(() => expect(screen.queryByText("recipe")).not.toBeInTheDocument());
    expect(screen.getByText("travel")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1);
  });
});
