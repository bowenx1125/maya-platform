# Maya Platform 当前状态与未审计代码报告

> 更新：2026-08-29  
> 清洗分支：`sol/repository-cleanup-handoff`  
> 结论：**仓库运行数据已清除，Demo 账号保留；Wave 3 大量代码仍未完成当前 HEAD 的 Full Sol G2/G3。**

## 1. 本次清洗做了什么

### 已从当前及未来 HEAD 删除

- `.env`；
- `data/` 与 `backend/data/`；
- SQLite、WAL、SHM；
- 本地创建的 Agent、AgentVersion、Debate、Turn、Interaction、Report 与 Translation 记录；
- KnowledgeSnapshot、group runtime Markdown 与生成音频；
- 个人声音样本与 `private-inputs/`；
- 临时锁、备份、日志、缓存；
- 历史 `archive/` 与 `outputs/`。

本次不改写旧 Git 历史。旧提交仍可能含此前上传的运行快照，但清洗分支当前树与未来提交不再允许这些文件。

### 保留

- 两份 Demo 账号与密码配置；
- 全部产品源码；
- 全部测试；
- Alembic 0001–0007；
- OpenAPI、WebSocket Schema、Fixtures 与生成 Client；
- 原始需求、历史合同、当前 Gate；
- `manual-tests/`；
- 根目录唯一共享状态表 `开发文档.xlsx`。

### 代码整理

- 重写 README 与 Project，使其成为当前成员可以直接使用的入口；
- 新增/更新文件地图、项目状态与清洗报告；
- 把 CI 从单个 Wave 2 串行 Job 升级为 Wave 3 多 Job 质量矩阵；
- 更新 Repository boundary 策略，只允许两份精确 Demo 账号文件含凭据；
- 大量 Python/TypeScript 文件做了机械格式化。

机械格式化不等于功能审计。格式化后的业务行为仍须由测试与 Sol 审计证明。

## 2. 如何理解“未审计”

未审计表示下面至少一项尚未完成：

- 当前 Commit 的全量格式、lint、类型与测试；
- 当前实现与 OpenAPI/WS/迁移合同的机械一致性；
- 独立 Sol 对权限、数据、状态机、迁移或恢复的风险审计；
- 真实浏览器主流程验收。

它不表示代码一定错误，也不表示代码可以删除。当前保留这些实现，是因为它们正是完成 Wave 3 Demo 所需的基础。

## 3. 高风险未审计范围

| 编号 | 路径 | 目标 | 当前状态 | 主要风险 | 完成前必须证明 |
| --- | --- | --- | --- | --- | --- |
| A1 | `backend/app/modules/interactions/**` | 互动窗口、匿名 Token、投票、弹幕、Open/Close | 有实现与测试；只有历史窄审 | Token/权限、并发、关闭后提交、事件顺序 | 角色权限、幂等、`BEGIN IMMEDIATE`、Token 伪造、submit-vs-close、commit 后事件 |
| A2 | `backend/app/modules/reports/**` | 弹幕洞察、报告 Manifest、Revision、下载 | 有实现与测试；无当前 Full G2 | nickname 泄漏、虚构计数/证据、失败覆盖旧成功 | 去昵称结构、精确计数、实际 TurnSource、600–900 词、Revision 与恢复 |
| A3 | `backend/app/modules/translations/**` | 派生翻译、缓存、批次、Job 与启动恢复 | 有实现与测试；存在 P1 疑点 | 共享 Entry follower 永久 pending、重复 Provider/Event | ready/failed 传播、Exactly-once、不同 Key 并发、重启、终态计数 |
| A4 | `backend/app/modules/debates/playback/**` | Pause/Resume、Finish、Reconnect、Replay、Wave 3 投影 | 部分历史审计；当前集成未完成 | 状态漂移、旧 Controller、媒体权限、Replay 越界 | CAS、重启、paused 恢复、Full/Partial Finish、逐段 Replay、不重复生成 |
| A5 | `backend/migrations/versions/0007_wave3_interaction_report.py` | Wave 3 表、索引、约束、Job owner | 当前迁移 Job 已通过；无最终功能 Diff 的独立审计 | 旧数据保护、降级残留、FK/索引语义 | fresh、repeat、populated、downgrade、re-upgrade、fingerprint、FK=0 与 Sol 复核 |
| A6 | `backend/app/main.py`、`core/models.py`、`core/config.py`、`core/db.py` | 路由注册、服务组合、任务恢复、数据库生命周期 | 跨模块改动存在 | 生命周期顺序、短 Session、任务重复调度 | 启停、恢复、连接池、路由与健康检查 |

## 4. 前端与合同未审计范围

| 编号 | 路径 | 目标 | 主要风险 | 必须验证 |
| --- | --- | --- | --- | --- |
| F1 | `frontend/components/interaction/**`、匿名课堂页 | 手机投票/弹幕与教师互动 | 两项状态绑定、Token 泄漏、关闭态错误、移动端溢出 | 360×800、独立 busy/success、no-store/no-referrer、关闭后不可用 |
| F2 | `frontend/components/report/**`、`history/**` | 报告、历史、Revision 与下载 | 旧成功被隐藏、渲染不安全、数据缺失 | ready/failed/generating、下载 Header、只读历史 |
| F3 | `frontend/components/translation/**`、`wave3/**` | 翻译批次与派生中文显示 | 失败后仍切换、译文重复、断线清空内容 | 成功才显示、英文权威、断线保留、批次终态 |
| F4 | `frontend/components/debate/stage/**`、教师控制页 | 播放舞台、Pause/Resume、Finish、Reconnect、Replay | 状态/页面集成不一致、大组件陈旧异步结果 | 页面级测试、刷新恢复、Replay speech/source、逐段 Next |
| C1 | `contracts/**` | OpenAPI、WS Schema、Fixtures、Allowlist | 合同与 FastAPI 漂移、业务 422 丢失、事件字段泄漏 | Redocly、hash、generated clean diff、server comparator、Ajv 反例 |
| C2 | `frontend/lib/api/generated/**`、`platform.ts` | 类型安全 API Client | 生成文件陈旧、手写 cast 掩盖合同缺陷 | 重新生成、零 Diff、全部 Wave 3 operation 可调用 |

## 5. 当前已识别的重点疑点

### P1：Translation follower 活性

当 Batch B 复用 Batch A 正在生成的 Translation Entry 时，B 可能保持 `pending`。A 进入 ready/failed 后，当前实现未被证明能够自动传播终态、重新计算 B 并唤醒其 Job。

目标修复：

1. Entry ready/failed 后传播给所有 follower item；
2. 重新计算 follower batch；
3. 事务提交后只调度真正可运行的 batch；
4. 不重复 Provider；
5. 不重复 terminal event；
6. restart 不留下永久 pending。

### P1：Playback 集成

需要集中验证：

- Pause 保存 cursor 且重启后可 Resume；
- Full Finish 允许 Interaction/Report/History/Replay；
- Partial Finish 保留已有 Turn但下游 fail-closed；
- Reconnect 每次点击只尝试一次；
- Replay 从不可变 Catalog 恢复 speech/source；
- Replay 每段进入 `waiting_next`；
- Replay 不新增 RAG/LLM/TTS Job。

### P1：当前 HEAD 的完整证明

当前第一轮清洗 CI 已暴露机械与行为问题，不能引用历史“曾经全绿”代替当前结果。

## 6. 清洗后第一轮 CI 结果

基线 Commit：`91c2af54501874486a27d18835547d6591655ad6`

### 已通过

- Repository policy；
- Prettier；
- Frozen OpenAPI；
- Generated Client check；
- Redocly；
- Response contract；
- Compose config；
- Wave 1–3 migration chain；
- Frontend ESLint；
- Frontend TypeScript；
- Backend Ruff format（141 files formatted）。

### Contracts 失败

`node scripts/test_route_surface.mjs` 报告：

```text
route fixture generator output is not deterministic
```

这表示 Route fixture 生成器在相同输入下不能保证稳定输出，尚不能作为可靠 clean-diff Gate。

### Frontend 失败

- 25 个测试文件：23 通过，2 失败；
- 162 个测试：157 通过，5 失败；
- Next build 因测试命令失败未运行。

失败测试：

1. `wave2-playback.test.tsx`：normal terminal replay order 未触发预期 snapshot refresh；
2. `wave2-playback.test.tsx`：reconnect 后 intermediate full replay waiting gate 未触发预期 refresh；
3. `wave2-playback.test.tsx`：旧测试仍期待自动 `reconnecting` 状态，与当前手动 Reconnect 产品决定冲突；
4. `wave2-playback.test.tsx`：reconnect 后 refreshed successor media action 未触发预期 refresh；
5. `wave3-playback-controls.test.tsx`：Replay retained catalog 未恢复 `Alpha speech`。

另有非阻塞警告：jsdom 不实现 media pause/load、WebGL context 不可用、React duplicate key 与调试输出。

### Backend 失败

Ruff lint 在 `backend/app/modules/debates/playback/sql_repository.py` 报告两处 E501：

- line 917：103 > 100；
- line 925：101 > 100。

由于 shell 使用 fail-fast：

- mypy 未运行；
- pytest 未运行。

### Aggregate

由于 Contracts、Frontend 与 Backend 未通过，Aggregate quality gate 失败。

## 7. 已有历史基础

- Wave 0、Wave 1、Wave 2 在 Mock 范围曾通过各自 Gate；
- Wave 3 做过机械检查与指定边界的窄范围审计；
- 这些历史结果可以作为设计背景，但不能替代清洗后当前 HEAD 的验证。

## 8. 当前总体进度判断

按“可稳定演示的完整 Mock Demo”而不是代码行数衡量：

- Wave 0–2：核心能力已经形成；
- Wave 3：主要模块已经写出，正在从“实现候选”走向“可证明版本”；
- Wave 4：尚未开始；
- 完整 Demo：未完成。

当前最准确的状态是：

```text
源码结构                 已清洗
运行记录                 已从当前 HEAD 删除
Demo 账号密码            保留
README/Project/开发文档   已同步
Wave 3 实现              大量存在
Wave 3 完整 CI           未通过
Wave 3 Full Sol G2       未通过
Wave 3 浏览器 G3         未通过
Wave 4                   未开始
完整 Demo                未完成
```

## 9. 下一步计划

1. 修 Route fixture 非确定性；
2. 修两个 Ruff E501，使 mypy 与 pytest 能运行；
3. 修复/更新 5 个前端播放测试；
4. 跑 Next build、mypy 与 full pytest；
5. 修 Translation follower 活性；
6. 收口 Playback/页面集成；
7. 根据最终 Diff 同步 OpenAPI、WS 与生成 Client；
8. 完整 CI 全绿；
9. Sol 对当前 SHA 做 Full G2；
10. 用户与 Main 完成教师/手机/Replay 浏览器 G3；
11. 再进入 Wave 4。

## 10. 本次没有做什么

本次是仓库清洗与状态诚实化，不是 Wave 3 功能修复：

- 没有修 Translation follower P1；
- 没有重新设计 Playback；
- 没有修改 0007 数据结构；
- 没有调用真实 Provider；
- 没有把历史窄审升级为 Full G2；
- 没有宣称完整 Demo 已完成。
