# Maya Platform 文件地图

本文档解释当前仓库主要目录和关键文件的职责。产品范围以 `Project.md` 为准，进度与未审计范围以 `docs/PROJECT_STATUS.md` 为准。

## 根目录

| 路径 | 作用 |
| --- | --- |
| `README.md` | 新成员入口：项目说明、启动方式、Wave 进度、质量命令和当前缺口。 |
| `Project.md` | 当前产品/工程权威：冻结边界、架构、Wave、Gate、风险和下一步。 |
| `AI文化互鉴教学平台-需求文档.md` | 最初业务需求的历史副本，不能越过 `Project.md` 直接扩大 Demo。 |
| `AGENTS.md` | Sol、Luna 和其他代码 Agent 的仓库工作规则。 |
| `UPLOAD_SCOPE.md` | 私有仓库允许/禁止保存的数据范围。 |
| `开发文档.xlsx` | Wave 状态、未审计代码与后续计划的结构化台账。 |
| `package.json` / `pnpm-lock.yaml` | JavaScript 工作区、统一脚本与固定依赖。 |
| `docker-compose.yml` | Caddy、Next.js、FastAPI 三容器本机/局域网拓扑。 |
| `.env.example` | 本地环境变量模板；真实 `.env` 不进入当前树。 |
| `.gitignore` / `.prettierignore` | 排除运行数据、构建产物、生成文件和需保持原样的资料。 |

## `.github/`

| 路径 | 作用 |
| --- | --- |
| `.github/workflows/quality.yml` | Wave 3 质量矩阵：仓库边界、契约、前端、后端、迁移和 Compose 独立执行。 |

CI 固定使用 Mock Provider，不读取真实模型凭据。

## `backend/`

### 基础文件

| 路径 | 作用 |
| --- | --- |
| `backend/pyproject.toml` | Python 3.12 依赖以及 Ruff、mypy、pytest 配置。 |
| `backend/uv.lock` | 固定 Python 依赖版本。 |
| `backend/Dockerfile` | FastAPI 后端容器构建。 |
| `backend/alembic.ini` | Alembic 迁移配置。 |

### `backend/app/core/`

| 文件 | 作用 |
| --- | --- |
| `config.py` | 校验 Demo、Provider、数据路径和课堂公共 Origin。 |
| `db.py` | SQLAlchemy Engine、Session 和 SQLite 边界。 |
| `models.py` | 共享 ORM 对象及跨模块关系。 |
| `errors.py` | 统一平台错误码和 HTTP 错误封装。 |

### `backend/app/modules/`

| 模块 | 主要职责 | 当前状态 |
| --- | --- | --- |
| `auth/` | 密码登录、Demo 快速登录、Session、CSRF、身份投影。 | 历史基线，最终 Demo 前需回归。 |
| `org/` | 课程、小组和成员只读关系。 | 历史基线。 |
| `agents/` | Agent、草稿、版本、发布、描述与安全删除。 | Wave 1 历史通过。 |
| `knowledge/` | Markdown、分块、Mock 向量、RAG 草稿和不可变快照。 | Wave 1 历史通过；真实检索质量后置。 |
| `avatars/` | 3D 模板和 Avatar 配置。 | 历史 Mock 验收。 |
| `voices/` | VoiceProfile、上传校验、试听、删除和兜底语义。 | Mock 路径；真实 TTS 延后。 |
| `debates/setup/` | 创建/修改辩论，冻结参与者、顺序、立场和版本。 | Wave 2 历史通过。 |
| `debates/generation/` | 两轮计划、RAG、模型输出校验和观点更新。 | Wave 2 历史通过。 |
| `debates/playback/` | WebSocket、控制权、媒体票据、Pause/Resume、Finish、Next、Replay。 | 最新增量未完成 Full 审计。 |
| `interactions/` | 匿名 Token、投票、弹幕、教师 Open/Close 和最终冻结。 | M13 已实现，窄审后仍待 Full G2。 |
| `reports/` | 匿名洞察、Maya 报告、Revision、引用和下载。 | M14 已实现，待 Full G2。 |
| `translations/` | 测试译文、不可变缓存、Batch/Job 和历史投影。 | M15 已实现，存在 follower 活性 P1。 |

模块常见文件：

- `router.py`：FastAPI 路由；
- `schemas.py`：Pydantic 请求/响应；
- `models.py`：模块 ORM；
- `service.py`：权威业务规则与事务；
- `policy.py`：可独立验证的确定性策略；
- `task_manager.py`：受控进程内后台任务。

### `backend/migrations/`

| 路径 | 作用 |
| --- | --- |
| `env.py` | Alembic 启动和 ORM 注册。 |
| `versions/0001...0006...py` | Wave 0–2 与 pre-Wave 3 历史迁移，不得为方便而改写。 |
| `versions/0007_wave3_interaction_report.py` | 互动、洞察、报告、翻译和 typed Job 结构。 |

### `backend/tests/`

重要 Wave 3 测试：

- `test_wave3_interactions.py`：Token、投票/弹幕、权限、幂等和竞态；
- `test_wave3_reports.py`：洞察、报告输入、Revision、字数和引用；
- `test_wave3_translations.py`：Manifest、缓存、Job 和恢复；
- `test_wave3_playback_controls.py`：Pause/Resume 与 Full/Partial Finish；
- `test_pw3_playback*.py`：pre-Wave 3 SQL/恢复回归。

## `frontend/`

### 路由

| 路径 | 作用 |
| --- | --- |
| `frontend/app/page.tsx` | 统一首页/登录。 |
| `frontend/app/student/**` | 学生 Agent、知识、版本和音色工作区。 |
| `frontend/app/teacher/**` | 教师检查、辩论创建、播放和互动报告页。 |
| `frontend/app/classroom/[access_token]/page.tsx` | 免登录手机投票/弹幕入口。 |

### 组件

| 路径 | 作用 | 当前状态 |
| --- | --- | --- |
| `components/session-provider/` | Session、CSRF 和角色边界。 | 历史基线。 |
| `components/locale/` | 中英界面切换。 | 历史基线。 |
| `components/avatar/` | 3D 预览与课堂状态。 | 历史 Mock 验收。 |
| `components/debate/setup/` | 辩论草稿和参与者选择。 | Wave 2 历史通过。 |
| `components/debate/stage/` | 课堂舞台、播放控制、事件恢复和 Replay。 | 最新增量待 Full 审计。 |
| `components/interaction/` | 教师互动面板、二维码和匿名手机表单。 | M13 待 Full 审计。 |
| `components/report/` | Maya 报告状态、Revision 和下载。 | M14 待 Full 审计。 |
| `components/history/` | 发言、来源、票数、弹幕和报告历史。 | M15 待 Full 审计。 |
| `components/translation/` | 按需测试翻译。 | M15 待 Full 审计。 |
| `components/wave3/` | 教师 Wave 3 组合层。 | 页面整合待 Full 审计。 |

### API 与测试

| 路径 | 作用 |
| --- | --- |
| `frontend/lib/api/generated/` | 从冻结 OpenAPI 生成的 TypeScript Schema/Client。 |
| `frontend/lib/api/platform.ts` | 页面使用的 Provider-neutral API 包装。 |
| `frontend/lib/i18n.ts` | 静态界面文案。 |
| `frontend/tests/` | Vitest/Testing Library 单元与集成测试。 |

Wave 3 重点前端测试：`wave3-interaction.test.tsx`、`wave3-report.test.tsx`、`wave3-history-translation.test.tsx`、`wave3-playback-controls.test.tsx` 和承载大量回归的 `wave2-playback.test.tsx`。

## `contracts/`

| 路径 | 作用 |
| --- | --- |
| `openapi-v0.1.yaml` / `.sha256` | 前后端唯一 HTTP 合同及冻结校验。 |
| `response-contract-allowlist.json` | 仅记录明确批准的响应差异。 |
| `route-surface-placeholders.json` | 已实现、缺失和基础设施路由分类。 |
| `ws-events.v1.schema.json` | 封闭的 WebSocket 事件联合 Schema。 |
| `fixtures/` | WS 正例/反例与契约输入。 |

## `scripts/`

| 路径 | 作用 |
| --- | --- |
| `bootstrap_local_demo.py` | 在空数据目录初始化预置课程/用户。 |
| `test_bootstrap_local_demo.py` | 验证初始化可重复和安全。 |
| `test_wave1_migration.py` / `test_wave2_migration.py` / `test_wave3_migration.py` | 各 Wave populated/fresh/down/up/FK/指纹检查。 |
| `check_frozen_openapi.mjs` | 检查 OpenAPI 与 Hash。 |
| `compare_route_surface.mjs` / `test_route_surface.mjs` | 对比/验证 FastAPI 路由表面。 |
| `generate_ws_schema.mjs` / `generate_ws_fixtures.mjs` | 生成 WS Schema/Fixture。 |
| `check_repo_boundary.mjs` | 检查 `.env`、运行数据和未授权私密文件。 |
| `test_repo_boundary.mjs` | 用临时探针验证边界检查。 |

## `config/`

| 路径 | 作用 |
| --- | --- |
| `repository-data-policy.json` | 当前私有仓库的精确数据白名单/黑名单。 |

## `backend/config/`

| 路径 | 作用 |
| --- | --- |
| `demo-accounts/accounts.private.md` | 用户明确要求保留的 Demo 账号/密码目录。 |
| `demo_users.yaml` | 旧 Demo 账号兼容配置。 |

这两份文件只用于私有团队 Demo，密码不得进入普通 API、前端 Bundle、WebSocket、错误或日志。

## 当前树禁止出现

- `.env`、API Key、Session Secret；
- `data/`、`backend/data/`、SQLite/WAL/SHM/备份；
- 已创建 Agent、Debate、Turn、互动、报告和翻译运行记录；
- 运行 Markdown、发布快照、生成音频、临时文件和锁；
- `private-inputs/`；
- `node_modules`、`.next`、`.venv`、缓存和 Coverage；
- `archive/`、`outputs/` 和重复表格。

新成员从 `README.md` 开始；编码前读 `Project.md`；接手未完成工作再读 `docs/PROJECT_STATUS.md` 和对应 Gate Packet。
