"""Build the single Maya Platform development-tracking workbook.

The workbook is a project-management view derived from the authoritative
README, Project handbook, and cleanup report. It contains no runtime data,
credentials, provider keys, personal input, or generated model content.

Run with Python 3.12 after installing ``openpyxl==3.1.5``::

    python scripts/build_development_workbook.py
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "开发文档.xlsx"

TITLE_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FILL = PatternFill("solid", fgColor="5B9BD5")
PASS_FILL = PatternFill("solid", fgColor="E2F0D9")
PARTIAL_FILL = PatternFill("solid", fgColor="FFF2CC")
FAIL_FILL = PatternFill("solid", fgColor="FCE4D6")


def title(sheet, text: str, end_column: int) -> None:
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_column)
    cell = sheet.cell(1, 1, text)
    cell.fill = TITLE_FILL
    cell.font = Font(bold=True, color="FFFFFF", size=16)
    cell.alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[1].height = 30


def table(sheet, rows: list[list[object]], widths: list[int]) -> None:
    for row in rows:
        sheet.append(row)
    for cell in sheet[3]:
        cell.fill = HEADER_FILL
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=4):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A4"


def status(cell, kind: str) -> None:
    fill = {"pass": PASS_FILL, "partial": PARTIAL_FILL, "fail": FAIL_FILL}[kind]
    color = {"pass": "385723", "partial": "7F6000", "fail": "9C0006"}[kind]
    cell.fill = fill
    cell.font = Font(bold=True, color=color)


def build() -> Workbook:
    workbook = Workbook()
    workbook.remove(workbook.active)

    sheet = workbook.create_sheet("项目总览")
    title(sheet, "Maya Platform 开发文档", 6)
    table(
        sheet,
        [
            ["字段", "当前值", "说明", "", "", ""],
            ["更新日期", "2026-08-29", "额度不足前的仓库清洗与 Wave 3 交接快照", "", "", ""],
            [
                "项目目标",
                "完成可演示的 AI 文化互鉴教学平台 Demo",
                "学生构建文化 Agent，教师主持证据可追溯的多 Agent 辩论，课后互动由 Maya 生成文明互鉴报告",
                "",
                "",
                "",
            ],
            ["顶层 Wave", "5 个：Wave 0–4", "Wave 1 细分为 1A / 1B / 1C", "", "", ""],
            [
                "当前阶段",
                "Wave 3 代码大量实现，Full G2/G3 未签",
                "项目已进入集成、审计与验收阶段，而不是早期开发",
                "",
                "",
                "",
            ],
            [
                "仓库清洗",
                "运行数据、已创建 Agent/Debate、数据库、生成音频和个人输入均从当前树移除",
                "只保留源代码、测试、契约、文档，以及两份 Demo 账号/密码配置",
                "",
                "",
                "",
            ],
            [
                "私有保留项",
                "Demo 账号和密码",
                "backend/config/demo-accounts/accounts.private.md；backend/config/demo_users.yaml",
                "",
                "",
                "",
            ],
            [
                "Provider 状态",
                "自动化与当前 Demo 默认全部 Mock",
                "真实 LLM / Embedding / TTS / Voice / Translation 属于未来独立 Gate",
                "",
                "",
                "",
            ],
            [
                "当前主要风险",
                "Translation follower 活性、播放增量、Wave 3 全链路未完成 Full 审计",
                "未审计不代表一定有错，但不能宣称完整 Demo 已完成",
                "",
                "",
                "",
            ],
        ],
        [18, 42, 68, 4, 4, 4],
    )

    sheet = workbook.create_sheet("Wave进度")
    title(sheet, "Wave 0–4 进度与结果", 6)
    table(
        sheet,
        [
            ["Wave", "核心模块", "目标", "当前结果", "证据等级", "仍需完成"],
            ["Wave 0", "运行骨架、认证、种子、数据库、契约、质量门", "建立可运行基础", "历史 G3 PASS", "历史自动化与合同记录", "最终 Demo SHA 上重新回归"],
            ["Wave 1A", "Agent 版本、Markdown RAG、教师检查", "创建并发布可追溯 Agent", "Mock 范围历史 G3 PASS", "历史测试与人工记录", "最终整站回归"],
            ["Wave 1B", "3D Avatar、Voice/TTS 边界", "数字人和语音能力", "Mock 路径通过；真实 TTS FAILED-DEFERRED", "Mock 证据；真实服务未通过", "未来另开真实语音 Gate"],
            ["Wave 1C", "UI / i18n / 页面外壳", "中英双语教学界面", "历史 G3 PASS", "历史前端与浏览器记录", "随 Wave 3 做整站回归"],
            ["Wave 2", "辩论创建、生成规则、播放大屏", "固定两轮、教师逐步推进、来源展示", "历史 Mock G3 PASS", "历史合同与测试", "复核最新 Pause/Resume、Finish、Replay 增量"],
            ["Wave 3", "课堂互动、匿名洞察、Maya 报告、历史与翻译", "完成辩论后的课堂闭环", "G1 大量实现；窄范围 G2 PASS；Full G2/G3 未签", "代码与专用测试存在，当前 SHA 仍有失败项", "修 P1、全量自动化、Full Sol 审计、浏览器 G3"],
            ["Wave 4", "跨模块集成、真实 Provider、最终 E2E", "完成最终 Demo", "未开始", "无", "仅在 Wave 3 G3 后进入"],
        ],
        [14, 34, 40, 42, 34, 48],
    )
    for row in range(4, 9):
        status(sheet.cell(row, 4), "pass")
    status(sheet.cell(9, 4), "partial")
    status(sheet.cell(10, 4), "fail")

    sheet = workbook.create_sheet("未审计代码")
    title(sheet, "大量未完成 Full 审计的代码清单", 6)
    table(
        sheet,
        [
            ["领域", "主要路径", "代码目标", "当前状态", "主要风险/缺口", "下一步验证"],
            ["M13 课堂互动", "backend/app/modules/interactions/**；frontend/components/interaction/**；frontend/app/classroom/**", "匿名二维码、投票、弹幕、教师实时汇总与关闭", "已实现；仅部分高风险边界做过窄审", "完整权限、并发、关闭竞态、移动端流程尚未 Full G2", "专用测试 + 全量后端 + 实际手机流程"],
            ["M14 Maya 报告", "backend/app/modules/reports/**；frontend/components/report/**", "去昵称洞察、不可变输入、600–900 词报告与修订", "已实现；输入边界曾窄审", "完整任务恢复、报告修订、下载与失败保留旧成功结果未全审", "策略/Manifest/任务恢复审计 + 浏览器报告流程"],
            ["M15 历史/翻译", "backend/app/modules/translations/**；frontend/components/history/**；frontend/components/translation/**", "按需中文测试表示、不可变英文历史和缓存复用", "已实现；存在已识别 P1", "共享 TranslationEntry 的 follower batch 可能永久 pending", "修终态传播、并发/重启测试、Sol 复审"],
            ["播放增量", "backend/app/modules/debates/playback/**；frontend/components/debate/stage/**", "Pause/Resume、完整/部分 Finish、手动 Reconnect、Replay catalog", "部分实现后因额度停止", "刷新/重启恢复、控制权围栏、Replay 不重复调用 Provider 尚未完整核验", "后端专项测试 + 页面集成 + 真实浏览器"],
            ["Wave 3 数据库", "backend/migrations/versions/0007_wave3_interaction_report.py；scripts/test_wave3_migration.py", "互动、洞察、报告、翻译与 typed Job 结构", "迁移链当前 CI 已通过", "仍需与最终业务修复后的同一 SHA 再验证", "最终 SHA fresh/repeat/down/up/fingerprint/FK"],
            ["契约与生成 Client", "contracts/**；frontend/lib/api/generated/**；scripts/generate_ws_*.mjs", "保持 FastAPI/OpenAPI/WS/前端类型一致", "OpenAPI、Redocly、生成 Client 当前通过；路由夹具确定性失败", "路由夹具仍是 pre-Wave3 形状", "修生成器与测试，重跑所有合同"],
            ["Wave 3 页面整合", "frontend/app/teacher/debates/**；frontend/components/wave3/**；frontend/lib/api/platform.ts", "组合播放、互动、报告、历史、翻译", "页面与 API 接线存在", "错误态、断线保留、译文切换、响应式未完整审计", "Vitest 页面级集成 + 6 视口浏览器"],
            ["质量流水线", ".github/workflows/quality.yml", "对当前代码提供可复现证明", "已升级为 Wave 3 多 Job Matrix", "前端仍有 5 个播放测试失败；后端在 lint 后尚未进入 mypy/pytest", "修机械错误后重跑，保留真实功能失败"],
        ],
        [20, 58, 40, 34, 54, 44],
    )

    sheet = workbook.create_sheet("CI状态")
    title(sheet, "清理分支当前自动化证据", 5)
    table(
        sheet,
        [
            ["检查", "结果", "已通过部分", "失败/未运行部分", "说明"],
            ["仓库数据边界", "PASS", "运行数据库、生成数据与未授权私密文件已清除", "", "Demo 账号/密码两份文件按用户决定保留"],
            ["格式与 OpenAPI", "PARTIAL", "Prettier、Frozen OpenAPI、Generated Client、Redocly、响应合同通过", "路由夹具确定性测试失败", "需更新到 66 个 Wave 3 operation / 0 placeholder"],
            ["后端", "PARTIAL", "Ruff format 141 文件通过", "Ruff lint 两处 E501；mypy/pytest 因此未运行", "先做两处机械换行，再暴露真实后端结果"],
            ["前端", "FAIL", "ESLint、TypeScript；157/162 Vitest 通过", "5 个播放/重连/Replay 测试失败；Build 未执行", "4 项与手动 Reconnect 合同相关，1 项需核对 Replay 真实行为"],
            ["迁移", "PASS", "Empty upgrade twice；Wave 1/2/3 populated preservation", "", "最终业务修复后仍需在最终 SHA 再跑"],
            ["Compose", "PASS", "docker compose config", "", "尚不等于三容器完整运行验收"],
            ["最终 Gate", "FAIL", "", "因合同、后端与前端未全绿", "仓库清理可完成，但不能签 Wave 3 G3"],
        ],
        [24, 16, 54, 54, 60],
    )
    for row, kind in [(4, "pass"), (5, "partial"), (6, "partial"), (7, "fail"), (8, "pass"), (9, "pass"), (10, "fail")]:
        status(sheet.cell(row, 2), kind)

    sheet = workbook.create_sheet("下一步")
    title(sheet, "完成 Demo 的推荐执行顺序", 7)
    table(
        sheet,
        [
            ["顺序", "任务", "负责人", "输出", "Gate", "当前状态", "完成条件"],
            [1, "合并仓库清洗基线", "Sol / 用户", "无运行数据、README、Project、状态报告、开发文档", "Cleanup", "本轮执行", "只保留 Demo 账号/密码两份私有配置；文档一致"],
            [2, "修 Translation follower 活性", "Luna", "代码与并发/重启测试", "Wave 3 Fix", "待做", "Follower 自动 ready/failed；无永久 pending；不重复 Provider"],
            [3, "修路由夹具与机械 lint", "Luna", "合同与后端检查继续运行", "G1.5", "部分处理中", "合同 Job 与 Ruff lint 通过"],
            [4, "核对播放/重连/Replay 失败", "Luna + Sol", "测试与必要的最小代码修复", "G1/G2", "待做", "保留手动 Reconnect 合同；真实 Replay 行为有证明"],
            [5, "Full Wave 3 Sol 审计", "Sol", "M13/M14/M15/Playback/契约审计报告", "G2", "待做", "P0=0、P1=0"],
            [6, "完整 Mock 浏览器竖切", "Main + 用户", "教师端、手机端、历史、翻译、Replay 验收", "G3", "待做", "主流程和 Partial Finish 均通过"],
            [7, "Wave 4 跨模块与真实服务", "Luna + Sol", "真实 Provider 独立 Gate 与最终 E2E", "G4/G5", "后置", "不得在 Wave 3 G3 前开始"],
        ],
        [10, 36, 20, 50, 16, 20, 58],
    )

    workbook.properties.title = "Maya Platform 开发文档"
    workbook.properties.subject = "Wave progress, unaudited code, CI state, and next steps"
    workbook.properties.creator = "Maya Platform team"
    return workbook


def main() -> None:
    workbook = build()
    workbook.save(OUTPUT)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
