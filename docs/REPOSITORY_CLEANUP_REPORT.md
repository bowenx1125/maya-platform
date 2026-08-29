# Repository Cleanup Report

## 1. 清洗目标

本次清洗把 `maya-platform` 从“包含本地运行快照的私有交接仓库”整理为“可继续开发和审计的私有源码仓库”。

用户要求：

- 保留 Demo 账号和密码；
- 保留产品代码、测试、合同与项目文档；
- 删除运行记录；
- 删除已创建 Agent 与 Debate；
- 删除数据库、快照、生成音频与个人音频；
- 删除 `.env`；
- 清楚标注大量尚未完整审计的 Wave 3 代码；
- 重写 README、Project 与开发状态表。

## 2. 删除内容

当前清洗分支从 HEAD 删除：

- `.env`；
- `data/`；
- `backend/data/`；
- 所有 SQLite、WAL、SHM；
- 本地 Agent、Debate、Turn、Report、Interaction、Translation 记录；
- KnowledgeSnapshot 与 group runtime Markdown；
- 当前辩论生成音频；
- `private-inputs/` 与个人声音样本；
- 临时锁、备份与运行残留；
- `archive/`；
- `outputs/`。

删除只影响当前及未来 HEAD，不重写旧 Git 历史。

## 3. 保留内容

- `backend/config/demo-accounts/accounts.private.md`；
- `backend/config/demo_users.yaml`；
- 全部后端、前端与迁移代码；
- 全部自动测试；
- `contracts/`；
- `manual-tests/`；
- 原始需求；
- 历史 pre-code contracts；
- 当前 Wave 3 Gate；
- 根目录更新后的 `开发文档.xlsx`。

## 4. 文档整理

- `README.md`：补充项目目标、已有功能、五个 Wave、安装、运行、测试、目录说明、当前 CI 与下一步；
- `Project.md`：从历史累积式记录收敛为当前权威项目手册；
- `AGENTS.md`：明确 Sol/Luna 分工与仓库数据边界；
- `UPLOAD_SCOPE.md`：调整为“账号可提交、运行数据与个人音频不可提交”；
- `docs/FILE_MAP.md`：解释主要文件与目录；
- `docs/PROJECT_STATUS.md`：列出清洗结果、当前 CI、未审计代码、风险与未来计划；
- `开发文档.xlsx`：更新 Wave、模块、未审计范围与下一步计划。

## 5. 工程策略整理

- `.gitignore` 忽略 `.env`、数据库、运行数据、个人输入、历史输出与构建产物；
- Repository boundary checker 只允许两份精确 Demo 账号路径；
- 其他 `.env`、数据库、音频、私有输入与源码中的 Key 继续被拒绝；
- Bootstrap 脚本在账号目录已存在时只创建 `.env`；
- CI 更新为 Wave 3 多 Job 质量矩阵，避免一个格式失败隐藏所有测试状态；
- 大量 Python/TypeScript 文件只做机械格式化，未把格式化标记为功能审计。

## 6. 第一轮 CI 结果

基线 `91c2af5`：

### 通过

- Repository policy；
- Prettier；
- Frozen OpenAPI；
- Generated Client check；
- Redocly；
- Response contract；
- Compose config；
- Wave 1–3 migration chain；
- Frontend ESLint 与 TypeScript；
- Backend Ruff format。

### 未通过

- Route fixture generator 非确定性；
- Frontend Vitest：157/162 通过，5 个播放/Replay 测试失败；
- Backend Ruff lint：`sql_repository.py` 两处 E501；
- mypy 与 pytest 因 Ruff fail-fast 未运行；
- Next build 因 Vitest 失败未运行；
- Aggregate quality gate 失败。

## 7. 本次没有做什么

本次是仓库清洗，不是 Wave 3 功能修复：

- 没有修 Translation follower P1；
- 没有重新设计 Playback；
- 没有修改 0007 数据结构；
- 没有调用真实 Provider；
- 没有把历史窄审升级为 Full G2；
- 没有宣称完整 Demo 已完成。

## 8. 清洗后的准确状态

```text
源码结构                 已清洗
运行记录                 已从当前 HEAD 删除
Demo 账号密码            保留
README/Project/开发文档   已同步
Wave 0–2                 历史 Mock 基线
Wave 3 代码              大量存在
Wave 3 Full CI           未通过
Wave 3 Full Sol G2       未通过
Wave 3 浏览器 G3         未通过
Wave 4                   未开始
完整 Demo                未完成
```
