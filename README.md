# Maya Platform

Maya 是一个本地优先的 AI 文化互鉴教学平台。学生以小组为单位构建带有 `AGENT.md`、Markdown RAG、3D 头脸和可选音色的文化智能体；教师选择 2–5 个已发布智能体进行固定两轮辩论；辩论结束后，课堂观众扫码参与匿名投票和带昵称弹幕，系统再生成去昵称洞察与 Maya 文明互鉴报告。

> **当前状态：Wave 3 收口与审计阶段。**  
> Wave 0–2 有历史 Mock Gate 证据；Wave 3 已有大量实现、迁移、合同和测试，但当前 Full CI 仍有前后端失败，Full Sol G2 与浏览器 G3 尚未签署。代码存在，不等于完整 Demo 已验收。

## 1. 开发路线：5 个 Wave

| Wave | 主要目标 | 当前结果 |
| --- | --- | --- |
| Wave 0 | 运行骨架、数据库、会话、种子、合同、质量门 | 历史 Mock Gate 通过 |
| Wave 1 | Agent/版本、Markdown RAG、3D、音色、UI/i18n | 历史 Mock Gate 通过 |
| Wave 2 | 辩论创建、生成、证据、播放、WebSocket、Replay | 历史 Mock Gate 通过 |
| Wave 3 | 投票/弹幕、洞察、Maya 报告、历史、翻译与播放增量 | 大量代码已实现，Full G2/G3 未通过 |
| Wave 4 | 跨模块集成、真实 Provider、局域网与完整 E2E | 未开始 |

最终目标是完成一个稳定、可解释、可重复演示的 Demo，而不是一次性实现正式版全部能力。

## 2. 当前已经实现的内容

### 学生制作端

- Demo 登录与身份切换；
- 小组工作区与多 Agent；
- `AGENT.md` 编辑；
- Markdown 上传、网页编辑和启用选择；
- 分块、Mock Embedding、向量检索和来源展示；
- 草稿测试聊天；
- 3D 头脸模板与参数；
- 可选 VoiceProfile 与兜底音色语义；
- 不可变 AgentVersion 与 KnowledgeSnapshot；
- 新版本创建和发布历史。

### 教师辩论端

- 查看课程已发布 Agent；
- 按点击顺序选择 2–5 个参辩 Agent，并自动分配 A–E；
- 固定两轮辩论；
- 指定或开放立场；
- 英文 Turn、来源和观点更新；
- WebSocket 状态同步；
- 教师逐段 Next；
- Pause / Resume；
- 完整或部分 Finish；
- 手动 Reconnect；
- 使用已保存内容的逐段 Replay。

### Wave 3 课堂闭环代码

- 匿名课堂 Token；
- 投票与弹幕独立提交；
- 教师打开/关闭互动；
- 票数与原始昵称弹幕；
- 去昵称弹幕洞察；
- 600–900 词 Maya 报告；
- 报告 Revision 与 Markdown 下载；
- 历史页面；
- 按需中文测试表示；
- 迁移 `0007_wave3_interaction_report.py` 与对应测试。

这些 Wave 3 代码仍需完整审计。详细范围见 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。

## 3. 清洗后的仓库数据策略

当前及未来 HEAD **保留**：

- 产品源码、测试、迁移与工程脚本；
- OpenAPI、WebSocket Schema、Fixtures 与生成 Client；
- `Project.md`、README、原始需求、Gate 与人工测试资料；
- 根目录唯一开发状态表 `开发文档.xlsx`；
- 两份 Demo 账号配置：
  - `backend/config/demo-accounts/accounts.private.md`
  - `backend/config/demo_users.yaml`

当前及未来 HEAD **不保留**：

- `.env` 与真实 Provider Key；
- SQLite、WAL、SHM；
- 本地创建的 Agent、Debate、Turn、Interaction、Report 与 Translation 记录；
- `data/`、`backend/data/`；
- KnowledgeSnapshot 与生成音频；
- 个人声音样本和 `private-inputs/`；
- 锁文件、日志、缓存、依赖与构建产物；
- 历史 `archive/` 与 `outputs/`。

本次清洗不改写旧 Git 历史；旧提交仍可能包含此前上传的运行快照。当前和未来提交不得再次加入这些文件。

## 4. 快速开始

### 环境要求

- Docker Desktop；
- Node.js `24.14.x`；
- pnpm `11.19.0`；
- Python `3.12`；
- `uv`；
- FFmpeg（运行音频相关后端测试时需要）。

### 第一次启动

```bash
git clone <private-repository>
cd maya-platform

corepack enable
corepack prepare pnpm@11.19.0 --activate
pnpm install --frozen-lockfile

pnpm bootstrap:local
docker compose up -d --build
docker compose ps
```

`pnpm bootstrap:local` 会保留仓库中的 Demo 账号目录，创建本地且被 Git 忽略的 `.env`，随机生成 Session Secret，并把所有 Provider 设为 `mock`。

打开：

```text
http://localhost:8080
```

日常启动与停止：

```bash
docker compose up -d
docker compose ps

docker compose stop
```

代码、依赖或 Dockerfile 改动后使用：

```bash
docker compose up -d --build
```

不要把 `docker compose down -v` 当作日常命令。

## 5. Demo 账号与本地配置

团队 Demo 账号和密码保存在：

```text
backend/config/demo-accounts/accounts.private.md
backend/config/demo_users.yaml
```

它们是这个私有团队仓库的明确例外。不要把密码复制到聊天、日志、截图或公开仓库。前端和普通 API 不能返回密码字段。

`.env` 不进入 Git。第一次启动脚本会创建，也可以手动执行：

```bash
cp .env.example .env
```

当前开发应保持：

```text
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock
TTS_PROVIDER=mock
VOICE_PROVIDER=mock
TRANSLATION_PROVIDER=mock
```

真实 Provider 调用不属于当前 Wave 3 收口范围，必须单独获得费用与风险授权。

需要手机扫码时，把 `CLASSROOM_PUBLIC_BASE_URL` 设置为电脑当前局域网地址，例如：

```text
http://192.168.x.x:8080
```

教师浏览器也必须使用同一个 Origin，不能在同一课堂流程中混用 `localhost` 与局域网地址。

## 6. 常用检查

### 仓库与合同

```bash
pnpm install --frozen-lockfile
pnpm exec prettier --check .

node scripts/check_repo_boundary.mjs
node scripts/test_repo_boundary.mjs
node scripts/check_frozen_openapi.mjs
node scripts/test_frozen_openapi.mjs
node scripts/check_generated_contracts.mjs
pnpm exec redocly lint --config contracts/redocly.yaml contracts/openapi-v0.1.yaml
node scripts/check_openapi_responses.mjs
node scripts/test_openapi_responses.mjs
node scripts/test_ws_events.mjs
node scripts/test_ws_commands.mjs
node scripts/check_generated_ws.mjs
node scripts/check_latin_script_tables.mjs
node scripts/test_route_surface.mjs
```

### 前端

```bash
pnpm --filter @maya/frontend lint
pnpm --filter @maya/frontend typecheck
pnpm --filter @maya/frontend test
pnpm --filter @maya/frontend build
```

### 后端

```bash
uv sync --directory backend --frozen

cd backend
uv run ruff format --check app tests migrations
uv run ruff check app tests migrations
uv run mypy app
uv run pytest
cd ..
```

### 迁移

```bash
uv run --directory backend python ../scripts/test_wave1_migration.py
uv run --directory backend python ../scripts/test_wave2_migration.py
uv run --directory backend python ../scripts/test_wave3_migration.py
```

### Docker

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs -f --tail=100
```

## 7. 目录与文件说明

```text
maya-platform/
├── README.md                     # 安装、使用、目录和当前状态
├── Project.md                    # 当前唯一项目权威说明
├── AI文化互鉴教学平台-需求文档.md  # 原始业务需求
├── 开发文档.xlsx                  # Wave、M01–M18、CI、未审计范围和下一步
├── AGENTS.md                     # AI/开发 Agent 的工作规则
├── UPLOAD_SCOPE.md               # 私库保留与禁止内容
├── backend/
│   ├── app/core/                 # 配置、数据库、错误、共享模型、生命周期
│   ├── app/modules/auth/         # 登录、Session、CSRF、Demo 身份
│   ├── app/modules/agents/       # Agent、草稿、发布和历史
│   ├── app/modules/knowledge/    # Markdown、分块、RAG 和快照
│   ├── app/modules/avatars/      # 3D Avatar 业务边界
│   ├── app/modules/voices/       # 音色注册、试听和删除
│   ├── app/modules/debates/      # 辩论创建、生成、播放和 WebSocket
│   ├── app/modules/interactions/ # Wave 3 匿名互动
│   ├── app/modules/reports/      # Wave 3 洞察与 Maya 报告
│   ├── app/modules/translations/ # Wave 3 测试翻译
│   ├── app/providers/            # Mock/真实供应商适配器
│   ├── migrations/               # Alembic 0001–0007
│   ├── tests/                    # 后端测试
│   └── config/                   # Demo 账号配置
├── frontend/
│   ├── app/                      # Next.js 学生、教师、课堂路由
│   ├── components/               # 页面和业务组件
│   ├── lib/api/                  # 平台 API 与生成 Client
│   ├── public/avatars/           # 本地 3D 资产
│   └── tests/                    # Vitest 测试
├── contracts/                    # OpenAPI、WS Schema、Fixtures、Allowlist
├── docs/
│   ├── FILE_MAP.md               # 主要文件职责
│   ├── PROJECT_STATUS.md         # 当前 CI、未审计代码、风险与路线
│   ├── REPOSITORY_CLEANUP_REPORT.md
│   ├── gates/                    # 当前 Gate
│   └── pre-code-contracts/       # 历史冻结合同
├── manual-tests/                 # 人工 RAG/课堂测试输入
├── scripts/                      # 初始化、合同、迁移和边界检查脚本
├── infra/                        # Caddy 配置
├── docker-compose.yml            # gateway/frontend/backend
└── .github/workflows/quality.yml # Wave 3 质量矩阵
```

更详细的说明见 [`docs/FILE_MAP.md`](docs/FILE_MAP.md)。

## 8. 当前自动化结果

当前机械证据基线：`e8a4124`。

### 已通过

- Repository policy；
- Prettier；
- Frozen OpenAPI、生成 Client、Redocly、Response contract、WS/route contract；
- Wave 1–3 migration chain；
- Compose configuration；
- 前端 ESLint 与 TypeScript；
- 后端 Ruff format、Ruff lint 与 strict mypy。

### 未通过

- 前端 Vitest：`157/162` 通过，5 个失败；
- 后端 pytest：`375/382` 通过，7 个失败；
- Aggregate quality gate 因前后端未全绿而失败。

前端 5 个失败分为：

- 1 个 legacy playback sequence / 手动 Reconnect 状态测试；
- 1 个仍要求 `Stop / Continue` 的旧测试，而当前产品接受 `Pause / Resume`；
- 3 个 Maya 报告 UI/投影测试：当前成功 Revision、失败态、无互动文案。

后端 7 个失败分为：

- 1 个 GitHub checkout 后 Demo credential 文件权限不是 `0600`；
- 5 个 WebSocket 测试 Origin 与 CI `CLASSROOM_PUBLIC_BASE_URL` 不一致；
- 1 个旧 restart matrix 仍期待 `paused → ready`，而当前合同要求 paused 持久保留。

其中多数属于 CI 环境或旧测试预期，但 3 个报告 UI 失败仍需审计，不能先假定只是测试错误。

## 9. 当前大量未完成 Full 审计的代码

| 范围 | 主要目录 | 目标 | 当前判断 |
| --- | --- | --- | --- |
| M13 课堂互动 | `backend/app/modules/interactions/**`、互动与匿名页面 | Token、投票、弹幕、Open/Close、实时汇总 | 大量实现，待 Full 权限/竞态审计 |
| M14 洞察与报告 | `backend/app/modules/reports/**`、报告 UI | 去昵称洞察、冻结输入、Maya 报告、Revision/下载 | 大量实现，报告 UI 仍有失败 |
| M15 历史与翻译 | `backend/app/modules/translations/**`、history/translation UI | 不可变英文历史、按需测试中文、缓存/恢复 | 大量实现；已识别 follower 活性 P1 |
| 播放增量 | `backend/app/modules/debates/playback/**`、`DebateStage` | Pause/Resume、Finish、Reconnect、Replay | 大量实现，需完整状态机复审 |
| 共享合同 | 0007、`contracts/**`、Generated Client | 统一 Wave 3 DB/API/WS/前端类型 | 机械合同通过，最终功能修复后需再生成审计 |
| 应用生命周期 | `backend/app/main.py` 与 TaskManager | Job/WS 启动恢复与关闭 | 已接线，需 restart/re-enqueue 集成审计 |

未审计不等于已知错误，也不等于可以删除；这些代码对应 Wave 3 目标功能，应先机械修复，再由 Sol 对最终 Diff 审计。

## 10. 下一阶段

1. 修 CI 机械环境：credential `0600`、统一测试 Origin、更新 paused restart 旧预期；
2. 更新前端旧 `Stop/Continue` 测试，并核对 legacy playback/manual Reconnect；
3. 修复并审计 3 个报告 UI 测试；
4. 修复 Translation shared-entry follower 永久 pending 风险；
5. 对 M13、M14、M15 与 Playback 做 Full Sol G2；
6. 最终重新生成 OpenAPI/WS/Client，复跑迁移和全量 CI；
7. 用干净本地数据库完成教师→匿名手机→报告→翻译→Replay 浏览器闭环；
8. Wave 3 G3 通过后，才进入 Wave 4 的真实 Provider 与完整 Demo。

## 11. 文档入口

- 当前权威范围：[`Project.md`](Project.md)
- 当前进度与未审计范围：[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- 本次仓库清洗报告：[`docs/REPOSITORY_CLEANUP_REPORT.md`](docs/REPOSITORY_CLEANUP_REPORT.md)
- 主要文件地图：[`docs/FILE_MAP.md`](docs/FILE_MAP.md)
- Wave 3 Gate：[`docs/gates/wave3/GATE_PACKET.md`](docs/gates/wave3/GATE_PACKET.md)
- 原始需求：[`AI文化互鉴教学平台-需求文档.md`](AI文化互鉴教学平台-需求文档.md)
