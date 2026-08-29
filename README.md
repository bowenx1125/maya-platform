# Maya Platform

Maya 是一个本地优先的 AI 文化互鉴教学平台。学生以小组为单位构建带有 `AGENT.md`、Markdown RAG、3D 头脸和可选音色的文化智能体；教师选择 2–5 个已发布智能体进行两轮证据化辩论；辩论结束后，课堂观众扫码参与匿名投票和带昵称弹幕，系统再生成去昵称洞察与 Maya 文明互鉴报告。

> **当前状态：Wave 3 收口前。**  
> Wave 0–2 的 Mock 基线有历史 Gate 证据；Wave 3 已存在大量实现和测试，但清洗后的当前分支尚未获得 Full CI、Full Sol G2 与浏览器 G3。代码存在，不等于完整 Demo 已验收。

## 1. 五个开发 Wave

| Wave   | 主要目标                                         | 当前结果                        |
| ------ | ------------------------------------------------ | ------------------------------- |
| Wave 0 | 运行骨架、数据库、会话、种子、合同、质量门       | 历史 Mock Gate 通过             |
| Wave 1 | Agent/版本、Markdown RAG、3D、音色、UI/i18n      | 历史 Mock Gate 通过             |
| Wave 2 | 辩论创建、生成、证据、播放、WebSocket、Replay    | 历史 Mock Gate 通过             |
| Wave 3 | 投票/弹幕、洞察、Maya 报告、历史、翻译和播放增量 | 大量代码已实现，未获 Full G2/G3 |
| Wave 4 | 跨模块集成、真实 Provider、局域网与完整 E2E      | 未开始                          |

最终目标是完成一个稳定、可解释、可重复演示的 Demo，而不是一次性实现所有正式版功能。

## 2. 当前已经有什么

### 学生制作端

- Demo 登录和身份切换；
- 小组工作区与多 Agent；
- `AGENT.md` 编辑；
- Markdown 上传、网页编辑与启用选择；
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
- 迁移 0007 与对应测试。

这些 Wave 3 代码仍需完整审计。详细范围见 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)。

## 3. 清洗后的仓库数据策略

当前及未来 HEAD **保留**：

- 产品源码、测试、迁移与工程脚本；
- OpenAPI、WebSocket Schema、Fixtures 与生成 Client；
- `Project.md`、README、原始需求、Gate 与人工测试资料；
- 根目录唯一共享状态表 `开发文档.xlsx`；
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

本次清洗不改写旧 Git 历史；旧提交仍可能包含此前上传的运行快照。当前分支和未来提交不得再次加入这些文件。

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

`pnpm bootstrap:local` 会：

- 保留仓库中已有的 Demo 账号目录；
- 创建本地且被 Git 忽略的 `.env`；
- 随机生成 Session Secret；
- 把所有 Provider 设为 `mock`；
- 不写入真实供应商 Key。

### 日常启动

```bash
docker compose up -d
docker compose ps
```

打开：

```text
http://localhost:8080
```

代码、依赖或 Dockerfile 改动后：

```bash
docker compose up -d --build
```

停止但保留本地数据：

```bash
docker compose stop
```

不要把 `docker compose down -v` 当作日常命令。

## 5. Demo 账号

团队 Demo 账号和密码保存在：

```text
backend/config/demo-accounts/accounts.private.md
backend/config/demo_users.yaml
```

它们是这个**私有团队仓库**的明确例外。不要公开仓库，也不要在聊天、日志或截图中复制密码。

前端只获得安全身份目录，不能读取密码字段。

## 6. 本地配置

`.env` 不进入 Git。第一次启动脚本会创建它，也可以从 `.env.example` 手动复制：

```bash
cp .env.example .env
```

默认应保持：

```text
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock
TTS_PROVIDER=mock
VOICE_PROVIDER=mock
TRANSLATION_PROVIDER=mock
```

真实 Provider 调用不属于当前 Wave 3 收口范围，必须单独获得费用和风险授权。

需要手机扫码时，把 `CLASSROOM_PUBLIC_BASE_URL` 设置为电脑当前局域网地址，例如：

```text
http://192.168.x.x:8080
```

教师浏览器也要使用同一个 Origin，不能在同一课堂流程中混用 `localhost` 与局域网地址。

## 7. 常用检查

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

## 8. 目录与文件说明

```text
maya-platform/
├── README.md                    # 安装、使用、目录和当前状态
├── Project.md                   # 当前唯一项目权威说明
├── AI文化互鉴教学平台-需求文档.md # 原始业务需求
├── 开发文档.xlsx                 # Wave、模块、未审计范围和下一步
├── AGENTS.md                    # AI/开发 Agent 的工作规则
├── UPLOAD_SCOPE.md              # 私库保留与禁止内容
├── backend/
│   ├── app/core/                # 配置、数据库、错误、共享模型、生命周期
│   ├── app/modules/auth/        # 登录、Session、CSRF、Demo 身份
│   ├── app/modules/agents/      # Agent、草稿、发布和历史
│   ├── app/modules/knowledge/   # Markdown、分块、RAG 和快照
│   ├── app/modules/avatars/     # 3D Avatar 业务边界
│   ├── app/modules/voices/      # 音色注册、试听和删除
│   ├── app/modules/debates/     # 辩论创建、生成、播放和 WebSocket
│   ├── app/modules/interactions/# Wave 3 匿名互动
│   ├── app/modules/reports/     # Wave 3 洞察与 Maya 报告
│   ├── app/modules/translations/# Wave 3 测试翻译
│   ├── app/providers/           # Mock/真实供应商适配器
│   ├── migrations/              # Alembic 0001–0007
│   ├── tests/                   # 后端测试
│   └── config/                  # Demo 账号配置
├── frontend/
│   ├── app/                     # Next.js 学生、教师、课堂路由
│   ├── components/              # 页面和业务组件
│   ├── lib/api/                 # 平台 API 与生成 Client
│   ├── public/avatars/          # 本地 3D 资产
│   └── tests/                   # Vitest 测试
├── contracts/                   # OpenAPI、WS Schema、Fixtures、Allowlist
├── docs/
│   ├── FILE_MAP.md              # 主要文件职责
│   ├── PROJECT_STATUS.md        # 清洗、进度、未审计代码与 CI 结果
│   ├── REPOSITORY_CLEANUP_REPORT.md
│   ├── gates/                   # 当前 Gate
│   └── pre-code-contracts/      # 历史冻结合同
├── manual-tests/                # 人工 RAG/课堂测试输入
├── scripts/                     # 初始化、合同、迁移和边界检查脚本
├── infra/                       # Caddy 配置
├── docker-compose.yml           # gateway/frontend/backend
└── .github/workflows/quality.yml# Wave 3 质量矩阵
```

更详细的文件地图见 [`docs/FILE_MAP.md`](docs/FILE_MAP.md)。

## 9. 当前自动化结果

清洗后的第一轮 CI（基线 `91c2af5`）已经证明：

- Repository policy：通过；
- Prettier：通过；
- Frozen OpenAPI、生成 Client、Redocly、Response contract：通过；
- Compose config：通过；
- 迁移链：通过；
- 前端 ESLint：通过；
- 前端 TypeScript：通过；
- 后端 Ruff format：通过。

尚未通过：

- Route fixture deterministic check；
- 前端 Vitest：25 个文件中 23 通过、2 失败；162 个测试中 157 通过、5 失败；
- 后端 Ruff lint：`sql_repository.py` 两处 E501；由于 shell fail-fast，mypy 与 pytest 尚未运行；
- Next build 未运行；
- Aggregate quality gate 因上述失败而失败。

这是一份真实的“已证明/未证明”边界，不是完整 Wave 3 通过声明。

## 10. 当前未完成和已知风险

重点未审计范围：

1. `backend/app/modules/interactions/**`
2. `backend/app/modules/reports/**`
3. `backend/app/modules/translations/**`
4. `backend/app/modules/debates/playback/**` 的 Wave 3 增量
5. 迁移 `0007_wave3_interaction_report.py`
6. Wave 3 教师、匿名、历史与翻译页面
7. OpenAPI、WebSocket 与生成 Client 的当前 HEAD 一致性
8. 应用启动恢复与任务生命周期

已识别但尚未修复的重点疑点：

- 复用同一个 Translation Entry 的 follower batch 可能永久停留在 `pending`；
- Pause/Resume、Full/Partial Finish、Reconnect 与 Replay 需要完整状态机复审；
- 0007 需要完整迁移矩阵与当前 HEAD 的独立审计。

## 11. 下一阶段

Wave 3 的收口顺序：

1. 修 Route fixture 非确定性和两个 Ruff E501；
2. 修复/更新 5 个前端播放测试，区分旧自动重连预期与当前手动 Reconnect 合同；
3. 运行 mypy、full pytest 与 Next build；
4. 修 Translation follower 活性；
5. 收口 Playback 与页面集成；
6. 同步 0007、OpenAPI、WS 与生成 Client；
7. 跑通完整 CI；
8. Full Sol G2，确保 P0=0、P1=0；
9. 完成教师端、手机端与 Replay 的浏览器 G3；
10. 再进入 Wave 4。

## 12. 开发方法

- Sol：项目总负责人、合同和风险审计；
- Luna：代码实现、测试、格式与 Docker；
- 用户：产品体验、费用授权与最终演示决定。

完整工作规则见 [`Project.md`](Project.md) 与 [`AGENTS.md`](AGENTS.md)。
