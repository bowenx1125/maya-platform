import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ReportMarkdown } from "../components/report/report-markdown";

afterEach(cleanup);

it("renders headings, emphasis, lists and tables instead of raw Markdown", () => {
  render(
    <ReportMarkdown>
      {
        "# 中文报告\n\n**RAG资料**\n\n- 第一项\n\n|观点|依据|\n|-|-|\n|判断|资料|"
      }
    </ReportMarkdown>,
  );
  expect(
    screen.getByRole("heading", { name: "中文报告", level: 1 }),
  ).toBeTruthy();
  expect(screen.getByText("RAG资料").tagName).toBe("STRONG");
  expect(screen.getByRole("listitem").textContent).toBe("第一项");
  expect(screen.getByRole("table")).toBeTruthy();
});

it("does not execute raw HTML or unsafe link protocols", () => {
  const { container } = render(
    <ReportMarkdown>
      {"<script>alert(1)</script>\n\n[link](javascript:alert%281%29)"}
    </ReportMarkdown>,
  );
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
});
