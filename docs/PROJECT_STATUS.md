# Maya Platform 项目状态与仓库清理报告

更新时间：2026-08-29  
当前主分支清理提交：`bf250437c6d5a538581825dfecc4c93f2452ba8a`

## 1. 本次工作的目的

由于当前开发额度不足，本轮不继续扩展 Wave 3 功能，而是先把此前的整机交接快照整理成一个可读、可继续开发、不会混入本机运行状态的源码仓库。清理后的 `main` 用作下一阶段开发基线，但不代表 Wave 3 已经完成或通过 Full G2/G3。

## 2. 已完成的仓库清理

当前 Git 树已经移除：

- `.env`、真实 Provider Key、Session Secret 等本机环境文件；
- `data/`、`backend/data/`、SQLite、WAL、SHM 和数据库备份；
- 本机创建的 Agent、AgentVersion、KnowledgeSnapshot、Debate、DebateTurn、Interaction、Report、Translation 等运行记录；
- 运行知识库、不可变快照副本、生成的课堂音频、临时目录和锁；
- `private-inputs/`，包括个人音频和供应商诊断输入；
- `archive/`、`outputs/` 和重复工作簿；
- JavaScript/Python 依赖目录、构建目录、缓存和 Coverage。

当前 Git 树保留：

- Backend、Frontend、迁移、测试、OpenAPI/WebSocket 契约和验证脚本；
- 原始需求历史副本与当前项目合同；
- 确定性的 `manual-tests/` Agent/RAG 夹具；
- 两份用户明确要求保留的私有 Demo 账号密码配置：
  - `backend/config/demo-accounts/accounts.private.md`；
  - `backend/config/demo_users.yaml`；
- 根目录唯一结构化开发台账 `开发文档.xlsx`。

Demo 密码只供私有团队登录使用。普通 API、前端 Bundle、生成 Client、WebSocket、错误响应和日志不得返回密码。

本轮没有重写 Git 历史或 force push。旧 Handoff Commit 仍作为历史快照存在，但当前 `main` 树已经清洗。

## 3. 文档与工程结构整理

本轮已经同步：

- `README.md`：项目目标、五个 Wave、目录结构、启动方法、质量命令、当前结果、已知缺口与最终 Demo 流程；
- `Project.md`：压缩为当前权威项目手册，保留产品边界、状态机、Wave、审计方法和后续顺序；
- `docs/FILE_MAP.md`：逐目录说明核心文件的职责和审计状态；
- `UPLOAD_SCOPE.md`：明确当前私库只保留源码、文档、测试、契约和两份 Demo 凭据；
- `config/repository-data-policy.json` 与仓库边界脚本：阻止 `.env`、运行数据库、音频和其他未授权私密数据再次进入当前树；
- `.github/workflows/quality.yml`：把旧 Wave 2 串行工作流升级为 Wave 3 多 Job 质量矩阵；
- `开发文档.xlsx`：同步 Wave 进度、清理结果、未审计代码、自动化证据和下一步。

## 4. 当前 Wave 进度

项目共有五个顶层 Wave；Wave 1 细分为 1A、1B、1C。

| Wave | 目标 | 当前结果 |
| --- | --- | --- |
| Wave 0 | 运行骨架、认证、数据库、契约、质量门 | 历史 G3 PASS |
| Wave 1A | Agent、不可变版本、Markdown RAG | 历史 Mock G3 PASS |
| Wave 1B | 3D Avatar、Voice/TTS 边界 | Mock 路径通过；真实 TTS `FAILED-DEFERRED` |
| Wave 1C | UI/i18n 与页面外壳 | 历史 G3 PASS |
| Wave 2 | 辩论创建、生成、播放大屏 | 历史 Mock G3 PASS |
| Wave 3 | 互动、匿名洞察、Maya 报告、历史、翻译 | 大量 G1 实现已存在；窄范围 G2 PASS；Full G2/G3 未签 |
| Wave 4 | 跨模块集成、真实 Provider、最终 E2E | 未开始 |

因此当前最准确的描述是：

> Wave 0–2 的 Mock 基础已经形成；Wave 3 的功能代码量较完整，但验证、审计和浏览器闭环明显落后于实现；Wave 4 尚未进入。完整 Demo 尚未完成。

## 5. 大量尚未完成 Full 审计的代码

### 5.1 M13 课堂互动

主要路径：

- `backend/app/modules/interactions/**`
- `frontend/components/interaction/**`
- `frontend/app/classroom/**`

目标：匿名课堂 Token、独立投票与弹幕、教师 Open/Close、实时票数、原始昵称弹幕和关闭时冻结最终输入。

当前状态：代码和专用测试已经存在；匿名 Token 完整性、幂等和部分竞态曾做过窄审，但全权限矩阵、所有写竞争和真实手机流程没有完成 Full G2/G3。

### 5.2 M14 匿名洞察与 Maya 报告

主要路径：

- `backend/app/modules/reports/**`
- `frontend/components/report/**`

目标：去除独立昵称字段、冻结弹幕/票数/证据输入、生成 600–900 词文明互鉴报告、保存不可变 Revision、保留旧成功版本并支持 Markdown 下载。

当前状态：输入去昵称和证据边界曾做过高风险窄审；完整任务恢复、Revision 并发、下载、失败路径和浏览器展示未完成 Full 审计。

### 5.3 M15 历史与按需翻译

主要路径：

- `backend/app/modules/translations/**`
- `frontend/components/history/**`
- `frontend/components/translation/**`

目标：基于精确英文 Hash 创建不可变翻译缓存和 Batch，在教师历史页按键显示明显标注的中文测试表示，且绝不回流 RAG、TTS、后续辩论或报告输入。

已识别 P1：当一个 Translation Batch 复用另一个 Batch 正在生成的 `TranslationEntry` 时，Follower Batch 可能在 Owner 完成或失败后仍长期停留在 `pending`。后续必须实现 Ready/Failed 终态传播、Follower 唤醒、Exactly-once 事件，以及并发与重启测试。

### 5.4 Wave 3 播放增量

主要路径：

- `backend/app/modules/debates/playback/**`
- `frontend/components/debate/stage/**`
- `frontend/app/teacher/debates/**`

目标：可恢复 Pause/Resume、完整与部分 Finish、单次手动 Reconnect、Replay Catalog 恢复文字/来源，以及每段 Replay 后等待教师 Next。

当前状态：代码部分实现并有专项测试。最近一次完整观察到的前端测试为 `157/162`：五项失败集中在播放/重连/Replay；其中四项可能仍按旧自动重连语义断言，一项可能是真实的 Replay 文字/来源恢复缺陷。不得在没有合同复核和浏览器证据时只为了绿色而删除测试。

### 5.5 0007 迁移、契约与页面组合

主要路径：

- `backend/migrations/versions/0007_wave3_interaction_report.py`
- `scripts/test_wave3_migration.py`
- `contracts/**`
- `frontend/lib/api/generated/**`
- `frontend/components/wave3/**`

目标：保存 Wave 3 派生数据和 typed Job 所有权；保持 FastAPI、OpenAPI、WebSocket 与前端生成类型一致；组合播放、互动、报告、历史和翻译页面。

当前状态：迁移机械检查在清理期间通过；路由基线已同步为 66 个已实现 Operation、0 个 Placeholder。最终功能修复后仍需在同一个 SHA 上重跑迁移、合同和生成代码检查，并做完整代码审计。

## 6. 自动化证据与限制

清理期间已经观察到：

- Repository policy PASS；
- Prettier、冻结 OpenAPI SHA、Generated Client、Redocly、Response Contract 曾通过；
- Wave 1/2/3 迁移保留性检查通过；
- `docker compose config --quiet` 通过；
- 前端 ESLint 与 TypeScript 通过；
- 最近一次完整观察的 Vitest 结果为 `157/162 PASS`；
- Backend Ruff format 通过，先前两条 E501 已在清理提交中修正。

合并提交 `bf250437...` 的主分支质量运行被取消：Repository policy 和 Compose 已完成成功，其他 Job 尚未形成统一终态。因此：

- 取消不等于功能失败；
- 取消也不等于通过；
- 当前没有一条覆盖合并 SHA 的完整全绿自动化证明；
- 本项目不能据此声明 Wave 3 G3 或完整 Demo 完成。

## 7. 推荐继续顺序

1. 修复 Translation Follower Ready/Failed 传播与活性 P1；
2. 逐项复核五项播放/重连/Replay 测试，区分过时断言与真实缺陷；
3. 在一个固定 Commit SHA 上完整运行 Contracts、Frontend、Backend、Migration 和 Compose；
4. 由 Sol 完成 M13、M14、M15、Playback 与共享契约的 Full Wave 3 G2 审计，要求 `P0=0 / P1=0`；
5. 用真实浏览器完成教师端、匿名手机端、刷新、断线、Partial Finish、报告、翻译和 Replay 的 Mock 竖切；
6. Main 签署 Wave 3 G3；
7. 只有之后才进入 Wave 4 和真实 LLM/Embedding/TTS/Voice/Translation Gate。

## 8. 交接结论

本轮的交付是一个干净、结构清楚、风险诚实的开发基线：

- GitHub `main` 已完成当前树清洗；
- Demo 账号密码保留；
- 本机运行记录、已创建 Agent/Debate 和个人输入不再属于源码基线；
- README、Project、文件地图、状态报告、仓库策略和开发台账已同步；
- 未审计 Wave 3 代码没有被删除，也没有被虚报为完成；
- 下一位开发者可以直接从 Translation P1 和五项播放测试继续，而不必重新考古整机运行数据。
