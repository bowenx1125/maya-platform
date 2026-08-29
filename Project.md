# Maya Platform 项目权威说明

> 最后更新：2026-08-29  
> 当前目标：完成可重复演示的 **Mock AI 文化互鉴教学平台 Demo**  
> 当前阶段：**Wave 3 收口前；大量代码已实现，但尚未获得当前 HEAD 的全量自动化证明与 Full Sol G2/G3**

---

## 0. 开发 Agent 必读规则

1. 每次开始工作，先完整阅读本文件，再阅读任务相关的 Gate、代码与测试。
2. 本文件描述当前有效决定；历史讨论不能反向覆盖本文件。
3. `AI文化互鉴教学平台-需求文档.md` 是原始需求基线。当前 Demo 的缩减范围以本文件为准。
4. 先确认范围、接口、状态机、权限、验收条件，再修改代码。
5. Demo 坚持“接口完整、功能简单、主流程可演示”，Mock 与真实 Provider 必须有清楚边界。
6. 不从参考仓库复制实现代码；只可参考交互、算法、分层与测试思路。
7. Demo 账号目录是本私有团队仓库的明确例外，可以提交；`.env`、数据库、本地创建的 Agent/Debate、快照、生成音频、个人音频及其他运行记录不得提交。
8. CI 与常规测试全部使用 Mock Provider，不得产生真实模型调用或费用。
9. Luna 负责编码、测试与局部重构；Sol 负责合同、风险审计与 Gate 判断。实现者不能审批自己的 Gate。
10. P0/P1 未关闭、当前 Commit 未通过确定性检查时，不得声称对应 Wave 或完整 Demo 已通过。

---

## 1. 项目是什么

Maya 是一个面向教学的本地优先 Web 平台。学生以小组为单位构建文化智能体，教师选择已发布智能体组织多 Agent 辩论；辩论结束后，课堂观众通过二维码匿名投票与发送带昵称弹幕，系统再生成去昵称洞察与 Maya 文明互鉴报告。

核心教学目标不是让系统“自动替学生做出漂亮答案”，而是让学生观察：

- `AGENT.md` 如何影响智能体身份与表达；
- Markdown 知识资料如何被分块、检索与引用；
- 已发布版本为什么需要不可变快照；
- 辩论状态、播放、证据、音色、互动与报告如何通过后端工作流协同；
- 相关 RAG 与无命中一般推理之间的真实差异。

---

## 2. Demo 用户与组织

当前 Demo 固定：

- 1 门课程；
- 1 名教师；
- 2 个学生小组；
- 每组 3 名学生；
- Demo 账号与密码保存在：
  - `backend/config/demo-accounts/accounts.private.md`
  - `backend/config/demo_users.yaml`

这些文件只用于本私有团队仓库与本地 Demo。前端与普通 API 不得返回密码字段。

课堂观众不属于账号体系。辩论完成后，观众使用随机访问 Token 打开匿名页面。

---

## 3. 当前冻结的产品范围

### 3.1 学生端

学生可以：

- 使用 Demo 身份登录；
- 查看本组工作区；
- 创建多个 Agent；
- 编写或上传 `AGENT.md`；
- 管理本组 Markdown 知识资料；
- 为每个草稿明确选择启用资料；
- 测试 RAG 命中与无命中；
- 选择有限的 3D 头脸配置；
- 可选绑定音色，缺失时使用系统兜底；
- 发布不可变 AgentVersion；
- 基于已发布版本创建下一版本。

发布后，历史版本、知识快照与既有辩论不得被后续草稿修改。

### 3.2 教师端

教师可以：

- 查看课程内当前与历史已发布 Agent 快照；
- 创建辩论草稿；
- 按点击顺序选择 2–5 个 Agent，系统自动分配 A–E；
- 使用固定 2 轮规则；
- 为参辩者指定支持、反对、中立或开放阐述；
- 启动辩论并逐段推进；
- 暂停与恢复播放；
- 完整结束或部分结束辩论；
- 完整结束后进入课堂互动、报告、历史与 Replay；
- 按需生成中文测试表示。

### 3.3 辩论规则

- 固定 2 轮；
- 每轮按 A→B→C→D→E；
- 第 1 轮形成观点并使用本 Agent 的 RAG；
- 第 2 轮回应此前发言、更新观点并提出问题；
- 最后一个计划 Turn 面向全班提出反思问题；
- 每段权威发言为英文；
- 每段 80–200 个英文单词，目标 160–185；
- 无相关证据时使用 `no_match + general_reasoning + 空来源`；
- 不联网补证据，不借用其他 Agent 的 RAG，不伪造引用。

### 3.4 播放与 Replay

- 浏览器不决定业务状态，后端状态机是唯一真相；
- `Pause / Resume` 是可恢复播放状态，不等于不可逆 `stopped`；
- 每个 Turn 播放完后进入 `waiting_next`，只有教师显式点击 Next 才能公开下一段；
- Replay 使用已保存的文字、来源与保留音频；
- Replay 每段仍等待 Next；
- Replay 不重新调用 RAG、LLM 或 TTS；
- 断线后不无限自动重连，教师可以手动 Reconnect；
- 完整 Finish 可以进入互动、报告、历史与 Replay；
- 部分 Finish 保留已有 Turn，但不开放匿名互动、Maya 报告、历史或 Replay。

### 3.5 课堂互动与 Maya 报告

- 只有完整辩论结束后，教师才能打开互动；
- 投票与弹幕是两个独立请求；
- 投票匿名，不存 nickname；
- 弹幕保存昵称与原文供教师大屏和历史查看；
- 刷新匿名页面后可以再次提交，这是 Demo 已确认边界；
- 教师关闭互动后，入口不可再次提交；
- 洞察层只接收消息 ID 与原始文本，不接收独立 nickname 字段；
- Maya 只读取：
  - 冻结辩论全文；
  - 实际使用的 TurnSource；
  - 最终匿名票数；
  - 经验证的匿名洞察；
- Maya 报告为 600–900 个英文词，不宣布赢家，不虚构票数或证据；
- 中文翻译只是按键触发的测试派生内容，不回流 RAG、TTS、辩论上下文或报告输入。

---

## 4. 技术架构

```text
Browser
  │
  ▼
Caddy gateway :8080
  ├── Next.js frontend :3000
  └── FastAPI backend :8000
         ├── SQLAlchemy + SQLite WAL
         ├── 本机文件存储
         ├── asyncio TaskManager
         ├── WebSocket Event Hub
         └── Mock / real Provider adapters
```

当前技术栈：

- Node.js 24.14；
- pnpm 11.19；
- Next.js 16；
- React 19；
- TypeScript 5.9；
- FastAPI；
- Python 3.12；
- SQLAlchemy；
- Alembic；
- SQLite；
- Caddy；
- Docker Compose；
- Vitest、pytest、Ruff、mypy、ESLint、Redocly、Ajv。

浏览器只调用平台 `/api/v1`；供应商 Key、外部音色 ID、存储绝对路径与 Provider 原始响应不得成为浏览器业务参数。

---

## 5. 数据与文件策略

### 5.1 Git 中保留

- 产品源码；
- 测试；
- Alembic 迁移；
- OpenAPI、WebSocket Schema 与生成 Client；
- 当前 Gate 文档；
- 原始需求；
- 人工测试输入；
- 根目录唯一开发状态表 `开发文档.xlsx`；
- 两份 Demo 账号配置。

### 5.2 Git 中不保留

- `.env`；
- SQLite、WAL、SHM；
- 本地创建的 Agent、Debate、Turn、Report、Interaction 与 Translation 数据；
- `data/` 与 `backend/data/`；
- 知识快照与生成音频；
- 个人音频与 `private-inputs/`；
- 运行备份、锁文件、日志与缓存；
- `archive/` 与历史 `outputs/`。

新机器通过迁移和 Demo seed 创建干净数据库。本次清洗不会重写旧 Git 历史，但当前及未来 HEAD 不再携带上述运行数据。

---

## 6. 五个 Wave

| Wave | 范围 | 当前状态 | 结论 |
| --- | --- | --- | --- |
| Wave 0 | 运行骨架、数据库、会话、种子、合同、质量门 | 历史通过 | Mock 基础已建立 |
| Wave 1 | Agent/版本、Markdown RAG、3D、音色、UI/i18n | 历史通过（Mock） | 学生制作链已实现 |
| Wave 2 | 辩论创建、生成、来源、播放、WebSocket、Replay | 历史通过（Mock） | 教师两轮辩论主链已实现 |
| Wave 3 | 互动、洞察、Maya 报告、历史、翻译、播放增量 | 大量代码已实现，未完整通过 | 当前收口重点 |
| Wave 4 | 跨模块集成、真实 Provider、局域网与完整 E2E | 未开始 | 完整 Demo 最终阶段 |

“历史通过”表示过去曾有对应 Gate 证据，不等于当前 HEAD 已重新获得全量自动化证明。

---

## 7. 当前真实进度

当前代码库已经包含：

- Wave 0–2 的主要 Mock 功能；
- Wave 3 迁移 `0007_wave3_interaction_report.py`；
- `interactions`、`reports`、`translations` 后端模块；
- 匿名课堂页面；
- 教师互动、报告、历史与翻译页面；
- Pause/Resume、Finish、Reconnect 与 Replay 增量；
- Wave 3 单元和集成测试；
- Wave 3 OpenAPI 与 WebSocket 合同。

当前仍不能声称 Full Wave 3 G3，因为：

1. 清洗后的当前分支尚未通过完整 CI；
2. Wave 3 只有历史窄范围审计，不是当前 HEAD 的 Full Sol G2；
3. Translation 共享 Entry 的 follower batch 存在已识别的活性疑点；
4. Playback、Finish、Replay 与页面集成仍需完整状态机审计；
5. 0007 迁移虽已通过当前 CI 的迁移 Job，但仍需结合最终功能 Diff 做独立审计；
6. 教师与手机真实浏览器闭环尚未最终签字。

清洗后第一轮 CI（基线 `91c2af5`）结果：

- 通过：Repository policy、Prettier、Frozen OpenAPI、生成 Client、Redocly、Response contract、Compose config、迁移链、ESLint、TypeScript、Ruff format；
- 失败：Route fixture deterministic check；
- 前端：25 个测试文件中 23 通过、2 失败；162 个测试中 157 通过、5 失败；Next build 因测试失败未运行；
- 后端：Ruff lint 在 `sql_repository.py` 两处 E501 失败；mypy 与 pytest 因 fail-fast 未运行；
- Aggregate quality gate 未通过。

完整列表见 `docs/PROJECT_STATUS.md`。

---

## 8. 未审计代码处理原则

未审计不等于已知错误，也不等于可以直接删除。

当前保留这些实现，是因为它们对应 Wave 3 目标功能；后续必须：

1. Luna 先修机械错误与已知缺陷；
2. 运行格式、lint、类型、单元、迁移、合同与 Docker 检查；
3. Sol 按风险审计当前 Diff；
4. P0/P1 关闭后才进入浏览器 G3；
5. 用户完成主观交互验收后，才能称 Wave 3 完成。

---

## 9. 开发与审计流程

```text
G0  Main 冻结合同
G0-S Sol 挑战高风险设计
G1  Luna 实现并自测
G1.5 确定性机械检查
G2  Sol 独立代码/契约审计
G3  Main + 用户浏览器验收
G4  跨模块集成
G5  真实服务与完整 Demo 验收
```

协作职责：

- **Sol**：项目总负责人、范围协调、状态机/权限/迁移审计、P0/P1 判断；
- **Luna**：本地编码、测试、Docker、格式与局部重构；
- **用户**：产品体验、真实服务费用授权、最终演示取舍。

---

## 10. 下一步

优先顺序：

1. 修 Route fixture 非确定性与两个 Ruff E501；
2. 修复/更新 5 个前端播放测试，区分旧自动重连预期与当前手动 Reconnect 合同；
3. 运行 mypy、full pytest 与 Next build；
4. 修复 Translation follower batch 的 ready/failed 传播与自动唤醒；
5. 完整复核 Pause/Resume、Full/Partial Finish、Reconnect、Replay Catalog；
6. 同步最终功能 Diff 对应的 0007、OpenAPI、WebSocket 与生成 Client；
7. 跑通完整 CI；
8. 执行 Full Sol G2；
9. 完成教师端、匿名手机端与 Replay 的真实浏览器 G3；
10. Wave 3 完成后，再进入 Wave 4 的真实 LLM/Embedding/TTS/Voice 与局域网验收。

任何真实 Provider 调用必须单独授权，不得由 CI 自动触发。

---

## 11. 相关文档

- `README.md`：安装、运行、目录与当前状态；
- `AI文化互鉴教学平台-需求文档.md`：原始业务需求；
- `docs/FILE_MAP.md`：主要文件职责；
- `docs/PROJECT_STATUS.md`：清洗结果、未审计代码、CI 与下一步；
- `docs/REPOSITORY_CLEANUP_REPORT.md`：本次仓库清洗记录；
- `docs/gates/wave3/GATE_PACKET.md`：Wave 3 当前 Gate；
- `docs/pre-code-contracts/`：历史冻结合同；
- `开发文档.xlsx`：模块、Wave、审计与下一步的唯一共享状态表。

---

## 12. 工作记录

### 2026-08-29：私库源码清洗

- 删除当前 Git HEAD 中的 `.env`；
- 删除 `data/`、`backend/data/` 与其中的数据库、Agent/Debate 运行记录、快照和生成音频；
- 删除个人音频和 `private-inputs/`；
- 删除历史 `archive/` 与 `outputs/`，只保留根目录更新后的 `开发文档.xlsx`；
- 保留 Demo 账号与密码目录；
- 保留全部产品代码、迁移、合同、测试和人工测试资料；
- 重写 README、Project、文件地图、项目状态和清洗报告；
- 更新仓库边界检查，使其符合“仅两份账号文件可提交、运行数据不可提交”的新策略；
- 将 CI 升级为 Wave 3 多 Job 质量矩阵；
- 对大量 Python/TypeScript 文件只做机械格式化，不把格式化视为功能审计；
- 未修复 Wave 3 业务代码，也未把未审计代码标为通过。
