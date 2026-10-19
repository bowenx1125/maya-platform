import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReportMarkdown } from "../components/report/report-markdown";
import {
  cleanReportCitations,
  reportLengthUnit,
} from "../lib/report-citations";

describe("report citations", () => {
  it("removes raw evidence tokens and keeps numbered citations", () => {
    const raw =
      "第1次发言的RAG资料：[evidence:evidence-949b4ccc510c544510d2f6f3536a5ef3]。 证据 [1] 支持 [evidence:x-1] 结论。";
    const cleaned = cleanReportCitations(raw);
    expect(cleaned).not.toContain("[evidence:");
    expect(cleaned).toBe("第1次发言的RAG资料：。 证据 [1] 支持 结论。");
  });

  it("leaves text without tokens untouched", () => {
    const text =
      "# Report\n\nA [1] citation.\n\n## Sources\n\n1. guide.md (turn 2)\n";
    expect(cleanReportCitations(text)).toBe(text);
  });

  it("renders a report without showing a raw token", () => {
    render(
      <ReportMarkdown label="report">
        {cleanReportCitations(
          "## 证据与论点\n\n平台指南 [evidence:evidence-aefea48c74c3aea72f3ac01011684d82] 要求资料要短。",
        )}
      </ReportMarkdown>,
    );
    const article = screen.getByRole("article", { name: "report" });
    expect(article.textContent).toContain("平台指南 要求资料要短。");
    expect(article.textContent).not.toContain("evidence");
  });

  it("labels Chinese report length in characters", () => {
    expect(reportLengthUnit("zh")).toBe("字");
    expect(reportLengthUnit("en")).toBe("words");
  });
});
