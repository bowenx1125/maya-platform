# Maya Platform 项目权威说明

> 最后更新：2026-08-29  
> 当前目标：完成可重复演示的 **Mock AI 文化互鉴教学平台 Demo**  
> 当前阶段：**Wave 3 收口与审计；大量代码已实现，Full CI、Full Sol G2 与浏览器 G3 尚未通过**

---

## 0. 开发 Agent 必读规则

1. 每次开始工作，先完整阅读本文件，再阅读任务相关 Gate、代码与测试。
2. 本文件描述当前有效决定；历史讨论不能反向覆盖本文件。
3. `AI文化互鉴教学平台-需求文档.md` 是原始需求基线，当前 Demo 缩减范围以本文件为准。
4. 先确认范围、接口、状态机、权限与验收条件，再修改代码。
5. Demo 坚持“接口完整、功能简单、主流程可演示”；Mock 与真实 Provider 必须有清楚边界。
6. 不从参考仓库复制实现代码；只可参考交互、算法、分层与测试思路。
7. Demo 账号目录是本私有团队仓库的明确例外，可以提交；`.env`、数据库、本地创建的 Agent/Debate、快照、生成音频、个人音频及其他运行记录不得提交。
8. CI 与常规测试全部使用 Mock Provider，不得产生真实模型调用或费用。
9. Luna 负责编码、测试和局部重构；Sol 负责合同、风险审计与 Gate 判断。实现者不能审批自己的 Gate。
10. P0/P1 未关闭、当前 Commit 未通过确定性检查时，不得声称对应 Wave 或完整 Demo 已通过。

---

## 1. 项目定义

Maya 是一个面向教学的本地优先 Web 平台。学生以小组为单位构建文化智能体，教师选择已发布智能体组织多 Agent 辩论；辩论结束后，课堂观众通过二维码匿名投票与发送带昵称弹幕，系统再生成去昵称洞察与 Maya 文明互鉴报告。

核心教学目标不是替学生自动生成“漂亮作品”，而是让学生观察：

- `AGENT.md` 如何影响身份与表达；
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

课堂观众不属于账号体系。完整辩论结束后，观众使用随机访问 Token 打开匿名页面。

---

## 3. 当前冻结产品范围

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

发布后的历史版本、知识快照与既有辩论不得被后续草稿修改。

### 3.2 教师端

教师可以：

- 查看课程内当前与历史已发布 Agent 快照；
- 创建辩论草稿；
- 按点击顺序选择 2–5 个 Agent，系统自动分配 A–E；
- 使用固定 2 轮规则；
- 为参辩者指定支持、反对、中立或开放阐述；
- 启动辩论并逐段推进；
- Pause / Resume；
- 完整 Finish 或部分 Finish；
- 完整结束后进入课堂互动、报告、历史与 Replay；
- 按需生成中文测试表示。

### 3.3 辩论与 RAG

- 固定 2 轮，每轮 A→B→C→D→E；
- 第 1 轮形成观点并使用本 Agent RAG；
- 第 2 轮回应此前发言、更新观点并提出问题；
- 最后一个计划 Turn 面向全班提出反思问题；
- 每段权威发言为英文，80–200 词，目标 160–185；
- 无相关证据时使用 `no_match + general_reasoning + 空来源`；
- 不联网补证据、不借用其他 Agent 的 RAG、不伪造引用。

### 3.4 播放与 Replay

- 后端状态机是唯一业务真相，浏览器不得自行推进状态；
- `Pause / Resume` 是可恢复状态，不等于不可逆 `stopped`；
- 每个 Turn 播放完进入 `waiting_next`，只有教师点击 Next 才公开下一段；
- 断线后不无限自动重连，教师可手动 Reconnect；
- Replay 使用已保存的文字、来源与保留音频，每段仍等待 Next；
- Replay 不重新调用 RAG、LLM 或 TTS；
- Full Finish 可以进入互动、报告、历史与 Replay；
- Partial Finish 保留已有 Turn，但不开放匿名互动、Maya 报告、历史或 Replay。

### 3.5 课堂互动、报告与翻译

- 只有完整辩论结束后，教师才能打开互动；
- 投票与弹幕是独立请求；
- 投票匿名，不存 nickname；
- 弹幕保存昵称与原文供教师大屏和历史查看；
- 刷新匿名页面后可以再次提交，这是 Demo 已确认边界；
- 教师关闭互动后，入口不可再次提交；
- 洞察层只接收消息 ID 与原始文本，不接收独立 nickname 字段；
- Maya 只读取冻结辩论全文、实际 TurnSource、最终匿名票数和经验证匿名洞察；
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

当前技术栈包括 Node.js 24、pnpm 11、Next.js 16、React 19、TypeScript 5.9、Python 3.12、FastAPI、SQLAlchemy、Alembic、SQLite、Caddy、Docker Compose、Vitest、pytest、Ruff、mypy、ESLint、Redocly 与 Ajv。

浏览器只调用平台 `/api/v1`。供应商 Key、外部音色 ID、绝对存储路径与 Provider 原始响应不得成为浏览器业务参数。

---

## 5. 仓库数据策略

### Git 中保留

- 产品源码、测试与 Alembic 迁移；
- OpenAPI、WebSocket Schema 与生成 Client；
- 当前 Gate、原始需求、人工测试资料；
- 根目录唯一状态表 `开发文档.xlsx`；
- 两份 Demo 账号配置。

### Git 中不保留

- `.env`；
- SQLite、WAL、SHM；
- 本地创建的 Agent、Debate、Turn、Report、Interaction 与 Translation 数据；
- `data/` 与 `backend/data/`；
- 知识快照与生成音频；
- 个人音频与 `private-inputs/`；
- 运行备份、锁文件、日志、缓存、`archive/` 与历史 `outputs/`。

新机器通过迁移和 Demo seed 创建干净数据库。本次清洗不重写旧 Git 历史，但当前和未来 HEAD 不再携带运行数据。

---

## 6. 五个 Wave

| Wave | 范围 | 当前状态 | 结论 |
| --- | --- | --- | --- |
| Wave 0 | 运行骨架、数据库、会话、种子、合同、质量门 | 历史通过 | Mock 基础已建立 |
| Wave 1 | Agent/版本、Markdown RAG、3D、音色、UI/i18n | 历史通过（Mock） | 学生制作链已实现 |
| Wave 2 | 辩论创建、生成、来源、播放、WebSocket、Replay | 历史通过（Mock） | 教师两轮主链已实现 |
| Wave 3 | 互动、洞察、Maya 报告、历史、翻译、播放增量 | 大量代码已实现，未完整通过 | 当前收口重点 |
| Wave 4 | 跨模块集成、真实 Provider、局域网与完整 E2E | 未开始 | 完整 Demo 最终阶段 |

“历史通过”表示过去存在相应 Gate 证据，不等于当前 HEAD 已重新获得全量自动化与审计证明。

---

## 7. 当前代码与机械证据

当前代码库包含：

- Wave 0–2 的主要 Mock 功能；
- Wave 3 迁移 `0007_wave3_interaction_report.py`；
- `interactions`、`reports`、`translations` 后端模块；
- 匿名课堂页面；
- 教师互动、报告、历史与翻译页面；
- Pause/Resume、Finish、Reconnect 与 Replay 增量；
- Wave 3 单元和集成测试；
- Wave 3 OpenAPI 与 WebSocket 合同。

当前机械证据基线：`e8a4124`。

已通过：Repository policy、Prettier、OpenAPI/生成 Client/Redocly/Response 与 WS 合同、Wave 1–3 migration chain、Compose config、前端 ESLint/TypeScript、后端 Ruff format/lint 与 strict mypy。

未通过：

- 前端 Vitest `157/162`，5 个失败；
- 后端 pytest `375/382`，7 个失败；
- Aggregate quality gate 失败。

前端失败包括 1 个 legacy playback/manual Reconnect 测试、1 个旧 Stop/Continue 测试，以及 3 个报告 UI/投影测试。后端失败包括 1 个 CI 文件权限问题、5 个 WebSocket Origin 测试环境不一致，以及 1 个旧 paused restart 预期。

多数后端失败与一个前端失败明显属于 CI/旧测试漂移；3 个报告 UI 失败必须先审计，不能直接当作测试错误。

---

## 8. 当前大量未完成 Full 审计的代码

### M13 课堂互动

- `backend/app/modules/interactions/**`
- `frontend/components/interaction/**`
- `frontend/app/classroom/**`

目标：匿名 Token、独立投票/弹幕、教师 Open/Close、实时汇总。需审计 Token 泄露、权限、幂等、提交与 Close 竞态、WS 重新授权。

### M14 洞察与 Maya 报告

- `backend/app/modules/reports/**`
- `frontend/components/report/**`

目标：去昵称洞察、冻结输入、Maya 报告、Revision 与下载。需审计 nickname 是否越界、计数与证据是否由代码权威计算、失败是否覆盖旧成功 Revision、报告 UI 状态。

### M15 历史与翻译

- `backend/app/modules/translations/**`
- `frontend/components/history/**`
- `frontend/components/translation/**`

目标：不可变英文历史、按需测试中文、缓存与恢复。已识别重点 P1：复用同一个 Translation Entry 的 follower batch 可能永久停留在 `pending`。

### Playback Wave 3 增量

- `backend/app/modules/debates/playback/**`
- `frontend/components/debate/stage/**`
- 教师 control/interaction 页面

目标：Pause/Resume、Full/Partial Finish、手动 Reconnect、Replay catalog。需完整状态机、控制版本、刷新、重启与页面集成审计。

### 共享合同、迁移与生命周期

- `backend/migrations/versions/0007_wave3_interaction_report.py`
- `contracts/**`
- `frontend/lib/api/generated/**`
- `backend/app/main.py` 与 TaskManager startup/recovery

机械合同和迁移 Job 已通过，但最终功能修复后仍需 clean diff、迁移指纹与独立审计。

---

## 9. 继续开发顺序

1. 修 CI 机械环境：Demo credential `0600`、统一 WebSocket test Origin、更新 paused restart 旧预期；
2. 更新旧 `Stop/Continue` 测试并核对 legacy playback/manual Reconnect；
3. 修复并审计 3 个报告 UI 测试；
4. 修复 Translation shared-entry follower 活性问题并补 ready/failed/restart/concurrency 测试；
5. 对 M13、M14、M15 与 Playback 做 Full Sol G2；
6. 最终重新生成 OpenAPI/WS/Client，复跑迁移和全量 CI；
7. 用干净本地数据库完成教师→匿名手机→报告→翻译→Replay 浏览器闭环；
8. Wave 3 G3 通过后，才进入 Wave 4 的真实 Provider 与完整 Demo。

---

## 10. Gate 规则

```text
G0   Main 冻结合同
G0-S Sol 设计挑战
G1   Luna 实现与自测
G1.5 确定性检查
G2   Sol 独立代码审计
G3   Main 集成与浏览器验收
G4   跨模块与真实服务集成
G5   完整本机/局域网 Demo 验收
```

- 实现者不能审批自己的 Gate；
- 机械错误先由工具/Luna 修复，再消耗 Sol 审计；
- P0/P1 必须由 Sol 复审关闭；
- Mock 结果不能冒充真实 Provider 验收；
- Wave 3 G3 未签前，不进入 Wave 4。

---

## 11. 当前准确状态牌

```text
源码结构                 已清洗
运行记录                 已从当前 HEAD 删除
Demo 账号密码            保留
README/Project/开发文档   已同步
Wave 0–2                 历史 Mock 基线
Wave 3 代码              大量存在
Wave 3 Full CI           未通过（Frontend 5 / Backend 7）
Wave 3 Full Sol G2       未通过
Wave 3 浏览器 G3         未通过
Wave 4                   未开始
真实 Provider            后置
完整 Demo                未完成
```
