import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Notebook, ResearchPage } from "../src/Research";
import { research } from "../src/researchApi";
vi.mock("../src/researchApi", () => ({
  research: {
    meta: vi.fn(),
    annotate: vi.fn(),
    family: vi.fn(),
    history: vi.fn(),
    jobs: vi.fn(),
    storage: vi.fn(),
    deleteBookmark: vi.fn(),
  },
}));
const meta = {
  notes: "Saved hypothesis <script>text only</script>",
  tags: ["baseline"],
  weight_bytes: 0,
  indexed_generation: 2,
  bookmarks: [],
};
function wrap(child: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {child}
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.mocked(research.meta).mockResolvedValue(meta);
  vi.mocked(research.jobs).mockResolvedValue([]);
});
describe("research workspace", () => {
  it("loads an editable notebook, keeps text inert, and saves normalized tags", async () => {
    vi.mocked(research.annotate).mockResolvedValue({});
    wrap(<Notebook id="example" />);
    const notes = await screen.findByLabelText("Notes", { exact: true });
    expect(notes).toHaveValue(meta.notes);
    expect(document.querySelector("script")).toBeNull();
    fireEvent.change(notes, { target: { value: "Updated observation" } });
    fireEvent.change(screen.getByLabelText("Tags, separated by commas"), {
      target: { value: " first, second, " },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save notes and tags" }),
    );
    await waitFor(() =>
      expect(research.annotate).toHaveBeenCalledWith(
        "example",
        "Updated observation",
        ["first", "second"],
      ),
    );
  });
  it("returns a bookmark's generation and agent selection to navigation", async () => {
    const bookmark = {
      id: "bookmark",
      title: "Selected ancestor",
      view: "Family Trees",
      generation: 1,
      agent: "1:2",
      notes: "",
      created: 1,
    };
    vi.mocked(research.meta).mockResolvedValue({
      ...meta,
      bookmarks: [bookmark],
    });
    const open = vi.fn();
    wrap(
      <ResearchPage
        page="Research Bookmarks"
        id="example"
        runs={[]}
        onOpen={open}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open view" }));
    expect(open).toHaveBeenCalledWith(bookmark);
  });
  it("hydrates the stored retention budget and requires explicit confirmation", async () => {
    vi.mocked(research.storage).mockResolvedValue({
      runs: [],
      disk_total: 1,
      disk_free: 1,
      backup_bytes: 0,
      research_jobs: 0,
    });
    wrap(
      <ResearchPage
        page="Storage Manager"
        id="example"
        runs={[]}
        onOpen={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Weight storage budget (MiB)")).toHaveValue(
        0,
      ),
    );
    expect(
      screen.getByRole("button", { name: "Apply retention" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I understand/ }));
    expect(
      screen.getByRole("button", { name: "Apply retention" }),
    ).toBeEnabled();
  });
});
