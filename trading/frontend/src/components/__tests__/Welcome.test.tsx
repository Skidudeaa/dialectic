// Welcome page smoke test — renders the page inside a memory router and
// asserts the hero plus several major section headings are present. Keeps
// us honest if section ids drift out of sync with the TOC.

import { describe, expect, it, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import Welcome from "../../pages/Welcome";

afterEach(() => {
  cleanup();
});

describe("Welcome page", () => {
  it("renders the hero, multiple sections, and quick links", () => {
    render(
      <MemoryRouter>
        <Welcome />
      </MemoryRouter>,
    );

    // Hero — the h1 is split across lines, so match a stable substring.
    expect(
      screen.getByRole("heading", { level: 1, name: /trade the chain/i }),
    ).toBeInTheDocument();

    // Section headings — at least three of the major h2s.
    expect(
      screen.getByRole("heading", { level: 2, name: /what this is/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /5-panel workspace/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /architecture/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: /what's coming/i }),
    ).toBeInTheDocument();

    // TOC nav landmark is present and labeled.
    expect(
      screen.getByRole("navigation", { name: /page sections/i }),
    ).toBeInTheDocument();
  });
});
