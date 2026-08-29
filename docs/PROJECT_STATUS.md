# Maya Platform 项目状态与仓库清理报告

更新时间：2026-08-29  
仓库：`bowenx1125/maya-platform`  
清洗合并提交：`bf250437c6d5a538581825dfecc4c93f2452ba8a`  
最终自动化验证代码提交：`e8a4124456cbe295e9a231c7a06e03e3314feec8`  
对应 GitHub Actions Run：`33256528200`

## 1. 当前结论

本轮已经把 Maya 从“包含本机运行现场的私有 Handoff 快照”整理为“可继续开发的源码、合同与测试仓库”。

当前准确状态：

```text
Repository cleanup        COMPLETE
Runtime/personal data     REMOVED FROM CURRENT TREE
Demo credentials          RETAINED AS REQUESTED
README / Project          SYNCHRONIZED
Development workbook      SYNCHRONIZED
Repository policy         PASS
Format and contracts      PASS
Migrations                PASS
Compose configuration     PASS
Frontend full job         FAIL
Backend full job          FAIL
Wave 3 Full G2            NOT SIGNED
Wave 3 G3                 NOT SIGNED
Complete Demo             NOT COMPLETE
```

仓库清洗完成不等于 Wave 3 完成。现有代码仍需修复、全量自动化、独立审计和真实浏览器验收。

## 2. 当前 Git 树已经删除的内容

当前 `main` 不再追踪：

- `.env` 和真实环境变量值；
- `data/`、`backend/data/`；
- SQLite 数据库、数据库备份、WAL、SHM；
- 本机创建的 Agent、AgentVersion、Debate、DebateTurn；
- Interaction、Vote、Barrage、Report、Translation 等运行记录；
- 运行时 KnowledgeSnapshot、RAG 文件和生成音频；
- `private-inputs/` 与个人音频；
- 临时锁、日志、缓存和构建产物；
- `archive/`、`outputs/` 和重复旧工作簿。

这些数据只从当前默认分支工作树删除。本轮没有重写旧 Git 历史，因此早期私有 Handoff 提交仍可在仓库历史中查看。

## 3. 当前 Git 树明确保留的内容

当前仓库保留：

- 后端、前端、迁移、测试、契约与脚本；
- `backend/config/demo-accounts/accounts.private.md`；
- `backend/config/demo_users.yaml`；
- 原始教师需求文档；
- 当前 `Project.md`；
- Wave 3 Gate Packet；
- 确定性的手工 Agent/RAG 测试资料；
- 根目录唯一开发工作簿 `开发文档.xlsx`。

两份 Demo 账号/密码配置是用户明确要求保留的私有团队 Demo 材料。它们不得进入普通 API 响应、WebSocket、生成浏览器代码、日志或错误信息。

## 4. 文档与结构整理

本轮完成：

- 重写 `README.md`，补齐项目介绍、五个 Wave、目录地图、首次启动、日常使用、质量命令、当前结果和目标 Demo 流程；
- 将 `Project.md` 收敛为当前可执行的项目手册；
- 新增 `docs/FILE_MAP.md`，解释主要目录和文件职责；
- 更新 `UPLOAD_SCOPE.md`、`AGENTS.md` 和仓库数据策略；
- 新增本状态报告和独立仓库清洗记录；
- 把 GitHub Actions 整理为仓库边界、格式/合同、前端、后端、迁移、Compose 与最终 Aggregate Job；
- 执行 Python 与前端源码的机械格式化；
- 更新根目录 `开发文档.xlsx`，覆盖项目总览、Wave 进度、未审计代码、CI 状态与下一步。

机械格式化只改变表现，不代表相关业务代码已经通过 Sol 审计。

## 5. Wave 进度

Maya 有五个顶层 Wave：`Wave 0` 到 `Wave 4`。Wave 1 分为 `1A / 1B / 1C`。

### Wave 0 — 基础运行

范围：运行骨架、认证、种子、数据库、契约和质量工具。  
结果：历史 G3 PASS；最终 Demo 提交仍需再次回归。

### Wave 1A — Agent、版本和 RAG

范围：Agent 创建、不可变版本、Markdown 资料、RAG 快照和教师检查。  
结果：历史 Mock G3 PASS。

### Wave 1B — 3D 与语音边界

范围：Avatar、VoiceProfile、TTS/Voice Provider 边界。  
结果：Mock 路径通过；真实 TTS 仍为 `FAILED-DEFERRED`，未经新 Gate 不重试。

### Wave 1C — UI 与 i18n

范围：中英界面、页面外壳和通用组件。  
结果：历史 G3 PASS。

### Wave 2 — 辩论与播放

范围：教师创建辩论、固定两轮生成、RAG 来源、教师逐步播放。  
结果：历史 Mock G3 PASS；后续 Pause/Resume、Finish、Reconnect、Replay 增量仍属于 Wave 3 收口范围。

### Wave 3 — 互动、Maya 报告、历史与翻译

范围：匿名课堂互动、弹幕洞察、Maya 报告、历史和按需中文测试表示。  
结果：大量 G1 实现已经存在，选定风险边界曾通过窄范围 G2；Full G2/G3 未签。

### Wave 4 — 最终集成与真实服务

范围：跨模块最终集成、单独授权的真实 Provider、完整 E2E 与 Demo 认证。  
结果：未开始。Wave 3 Full G3 前不得进入。

## 6. 未完成 Full 审计的主要代码

### 6.1 M13 课堂互动

路径：

- `backend/app/modules/interactions/**`
- `frontend/components/interaction/**`
- `frontend/app/classroom/**`

目标：签名匿名入口、投票与弹幕独立提交、教师实时汇总、关闭后的精确冻结。

当前：代码和专项测试存在；Token、幂等和部分并发边界曾做窄审，但完整权限矩阵、关闭竞态和移动端真实流程未完成 Full G2/G3。

### 6.2 M14 匿名洞察与 Maya 报告

路径：

- `backend/app/modules/reports/**`
- `frontend/components/report/**`

目标：去除独立昵称字段、冻结洞察输入、只使用实际引用证据、生成 600–900 词英文文明互鉴报告、维护不可变 Revision 和安全下载。

当前：主体实现存在；完整 Job 恢复、Revision 并发、失败保留旧成功、下载与浏览器流程尚未 Full 审计。

### 6.3 M15 历史与按需翻译

路径：

- `backend/app/modules/translations/**`
- `frontend/components/history/**`
- `frontend/components/translation/**`

目标：保留权威英文历史，教师按键生成明确标记的中文测试表示，并按精确原文 Hash 复用翻译缓存。

已知 P1：Follower Batch 复用另一个正在生成的 TranslationEntry 时，Owner 到达 ready/failed 后，Follower 可能永久停在 pending。后续必须传播终态、重算 Batch/Job、只调用一次 Provider，并补并发与重启测试。

### 6.4 Playback 的 Wave 3 增量

路径：

- `backend/app/modules/debates/playback/**`
- `frontend/components/debate/stage/**`
- 教师 Debate 控制与互动页面

目标：可恢复 Pause/Resume、完整/部分 Finish、单次手动 Reconnect、Replay 恢复文字和来源、逐段等待 Next，并保证 Replay 不重复调用 RAG/LLM/TTS。

当前：实现与专项测试存在，但状态机、Controller 围栏、刷新/重启恢复、页面集成和真实浏览器行为尚未最终核验。

### 6.5 Wave 3 迁移与集成

路径：

- `backend/migrations/versions/0007_wave3_interaction_report.py`
- `scripts/test_wave3_migration.py`
- `backend/app/main.py`
- 共享模型与 Projection 接线

目标：加入互动、洞察、报告、翻译和 typed Job owner，同时保护 0001–0006 数据。

当前：最终验证提交的 Migration Job 已通过；业务修复后仍需在最终候选 SHA 再跑同一完整矩阵。

### 6.6 OpenAPI、WebSocket 与前端 Client

路径：

- `contracts/**`
- `frontend/lib/api/generated/**`
- `frontend/lib/api/platform.ts`
- `frontend/components/wave3/**`
- `frontend/app/teacher/debates/**`
- `scripts/generate_ws_*.mjs`

目标：后端、浏览器 DTO、错误码和实时事件只有一套封闭合同。

当前：最终验证提交上的 Format and contracts Job 已通过；后续业务修复仍需重新生成并检查 clean diff。

## 7. 最终自动化结果

验证对象：`e8a4124456cbe295e9a231c7a06e03e3314feec8`  
Workflow Run：`33256528200`

### 7.1 已通过

- Repository policy；
- Prettier；
- Frozen OpenAPI；
- Generated Client；
- Redocly；
- 显式响应合同；
- Route surface fixtures；
- WebSocket 正反 Schema/fixture；
- Latin-script generated table；
- Empty database upgrade twice；
- Wave 1/2/3 populated migration preservation；
- Docker Compose configuration；
- Backend Ruff format；
- Backend Ruff lint；
- Frontend ESLint；
- Frontend TypeScript。

### 7.2 后端失败

Backend Job 在 mypy 阶段失败，共 3 个错误：

1. Playback idempotency body 中 `expected_current_turn_id` 的类型为 `str | None`，而当前帮助函数签名未接受该类型；
2. `translations.__init__` 导出的 `TranslationInputManifestV1` 未被 mypy 识别为 manifest 模块显式属性；
3. `translations.__init__` 导出的 `build_translation_manifest` 同样未被 mypy 识别。

因为 mypy 失败，full backend pytest 没有在该 Job 中继续执行，因此不能声称后端全量测试通过。

### 7.3 前端失败

最近一次完整前端结果：

- ESLint：通过；
- TypeScript：通过；
- Vitest：157/162 通过，5 个失败；
- 失败集中在 `frontend/tests/wave3-playback-controls.test.tsx`；
- 主要覆盖手动 Reconnect、Replay 文字/来源恢复和 Pause/Resume 控制；
- Next production build 因测试失败未执行。

不能直接删除失败测试。下一步应根据当前冻结合同判断旧测试是否仍要求自动重连，或实现是否确实遗漏手动重连/Replay 行为。

### 7.4 最终 Gate

Backend 与 Frontend Job 失败，因此 Aggregate 未通过。Full Wave 3 G2/G3 仍然未签。

## 8. 推荐继续顺序

1. 修复 M15 Translation follower 终态传播，增加 Owner-ready、Owner-failed、混合、并发、重启和 Exactly-once 测试。
2. 修复 3 个后端 mypy 错误并运行 full pytest。
3. 审查 5 个前端播放测试失败，保留“断线后由教师手动 Reconnect，不无限自动重连”的当前产品合同。
4. 完成 Next production build。
5. 在一个最终候选 SHA 上重跑所有仓库、合同、前端、后端、迁移和 Docker 检查。
6. 由独立 Sol 完成 Full Wave 3 G2，要求 P0=0、P1=0。
7. 用真实浏览器完成教师、匿名手机端、报告、历史、翻译、Replay 和 Partial Finish 的 desktop/tablet/mobile G3。
8. Wave 3 Full G3 后，才进入 Wave 4 和任何真实 Provider 工作。

## 9. 项目交接原则

- Luna 负责实现、机械修复、测试、Docker 与提交；
- Sol 负责架构、风险、审计、Gate 与项目协调；
- 实现者不能批准自己的 Gate；
- Mock 成功不得冒充真实 Provider 成功；
- 触及权限、迁移、状态机、不可变历史、Provider 或费用的修改必须单独审计；
- 当前清洗基线不携带个人运行数据，新开发者从空的本地 `data/` 开始。
