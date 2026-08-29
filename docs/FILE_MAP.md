# Maya Platform 文件地图

本文档解释当前仓库中主要目录和关键文件的职责。它不替代 `Project.md` 的产品合同，也不替代 `docs/PROJECT_STATUS.md` 的进度与审计状态。

## 根目录

| 路径                             | 作用                                                                       |
| -------------------------------- | -------------------------------------------------------------------------- |
| `README.md`                      | 新成员入口：项目是什么、怎样启动、Wave 进度、常用命令和当前已知缺口。      |
| `Project.md`                     | 当前产品与工程权威摘要：冻结边界、状态机、Wave 规划、审计方法和下一步。    |
| `AI文化互鉴教学平台-需求文档.md` | 最初业务需求的历史副本；不能越过 `Project.md` 直接作为当前 Demo 实现清单。 |
| `AGENTS.md`                      | Sol、Luna 和其他代码 Agent 在仓库内工作的规则。                            |
| `UPLOAD_SCOPE.md`                | 当前私有团队仓库允许和禁止保存的数据范围。                                 |
| `开发文档.xlsx`                  | 面向项目管理的结构化开发文档：Wave 状态、未审计代码和下一步。              |
| `package.json`                   | JavaScript 工作区版本、依赖和统一脚本入口。                                |
| `pnpm-lock.yaml`                 | 固定 JavaScript 依赖解析结果。                                             |
| `docker-compose.yml`             | 本机/局域网 Demo 的 Caddy、Next.js、FastAPI 三容器拓扑。                   |
| `.env.example`                   | 本地环境变量模板；真实 `.env` 不进入当前仓库树。                           |
| `.gitignore`                     | 排除环境文件、运行数据库、构建产物和缓存。                                 |
| `.prettierignore`                | 排除生成文件、二进制和需保持原样的历史/高风险文件。                        |

## `.github/`

| 路径                            | 作用                                                                       |
| ------------------------------- | -------------------------------------------------------------------------- |
| `.github/workflows/quality.yml` | Wave 3 质量矩阵；独立运行仓库边界、契约、前端、后端、迁移和 Compose 检查。 |

CI 固定使用 Mock Provider，不读取或调用真实模型服务。

## `backend/`

### 基础文件

| 路径                     | 作用                                           |
| ------------------------ | ---------------------------------------------- |
| `backend/pyproject.toml` | Python 3.12 依赖以及 Ruff、mypy、pytest 配置。 |
| `backend/uv.lock`        | 固定 Python 依赖版本。                         |
| `backend/Dockerfile`     | FastAPI 后端容器构建定义。                     |
| `backend/alembic.ini`    | Alembic 迁移配置。                             |

### `backend/app/core/`

| 文件        | 作用                                                             |
| ----------- | ---------------------------------------------------------------- |
| `config.py` | 读取并校验运行配置；决定 Demo、Provider、路径和公共课堂 Origin。 |
| `db.py`     | SQLAlchemy Engine、Session 与 SQLite 运行边界。                  |
| `models.py` | 共享核心 ORM 对象与跨模块关系。                                  |
| `errors.py` | 统一平台错误码和 HTTP 错误封装。                                 |

### `backend/app/modules/`

| 模块                  | 作用                                                                | 当前审计状态                              |
| --------------------- | ------------------------------------------------------------------- | ----------------------------------------- |
| `auth/`               | 用户名/密码、Demo 快速登录、Session、CSRF 和身份投影。              | 历史审计通过；最终 Demo 前仍需全量回归。  |
| `org/`                | 课程、小组和成员只读关系。                                          | 历史基线。                                |
| `agents/`             | Agent 身份、草稿、版本、发布、描述与安全删除。                      | Wave 1 历史通过。                         |
| `knowledge/`          | Markdown 文档、分块、Mock 向量、RAG 草稿与不可变快照。              | Wave 1 历史通过；真实检索质量后置。       |
| `avatars/`            | 3D 模板和 Avatar 配置。                                             | Mock/本地路径历史通过。                   |
| `voices/`             | VoiceProfile、上传校验、试听、删除和兜底语义。                      | Mock 路径通过；真实 TTS 延后。            |
| `debates/setup/`      | 教师创建/修改辩论，固定参与者、顺序、立场和版本快照。               | Wave 2 历史通过。                         |
| `debates/generation/` | 两轮发言计划、RAG 检索、模型输出校验和位置更新。                    | Wave 2 历史通过。                         |
| `debates/playback/`   | WebSocket、控制权、媒体票据、Pause/Resume、Finish、Next 和 Replay。 | 最新 Wave 3 增量未完成 Full 审计。        |
| `interactions/`       | 匿名课堂 Token、投票、弹幕、教师 Open/Close 和最终输入冻结。        | M13 已实现；仅部分高风险边界审计。        |
| `reports/`            | 匿名弹幕洞察、Maya 报告、Revision、引用和下载。                     | M14 已实现；Full 审计未完成。             |
| `translations/`       | 按需测试译文、不可变缓存、Batch/Job 和历史投影。                    | M15 已实现；存在 follower-batch 活性 P1。 |

每个业务模块通常包含：

- `router.py`：FastAPI 路由与 HTTP 合同；
- `schemas.py`：Pydantic 请求/响应对象；
- `models.py`：模块 ORM 对象；
- `service.py`：权威业务规则与事务；
- `policy.py`：可独立验证的确定性策略；
- `task_manager.py`：受控进程内后台任务（仅部分模块需要）。

### `backend/migrations/`

| 文件                                        | 作用                                                |
| ------------------------------------------- | --------------------------------------------------- |
| `env.py`                                    | Alembic 启动和 ORM 元数据注册。                     |
| `versions/0001...0006...py`                 | Wave 0–2 与 pre-Wave 3 历史迁移；不得为方便而改写。 |
| `versions/0007_wave3_interaction_report.py` | Wave 3 互动、洞察、报告、翻译和 typed Job 结构。    |

### `backend/tests/`

测试文件按功能波次命名。重要 Wave 3 文件包括：

- `test_wave3_interactions.py`：匿名 Token、投票/弹幕、权限、幂等和竞态；
- `test_wave3_reports.py`：匿名洞察、报告输入、Revision、字数和引用；
- `test_wave3_translations.py`：Manifest、缓存复用、Job 与重启恢复；
- `test_wave3_playback_controls.py`：Pause/Resume 与 Full/Partial Finish；
- `test_pw3_playback*.py`：pre-Wave 3 SQL 与恢复回归。

## `frontend/`

### 应用路由

| 路径                                             | 作用                                                |
| ------------------------------------------------ | --------------------------------------------------- |
| `frontend/app/page.tsx`                          | 统一首页和登录入口。                                |
| `frontend/app/student/**`                        | 学生 Agent、知识库、版本和音色工作区。              |
| `frontend/app/teacher/**`                        | 教师 Agent 检查、辩论列表、创建、播放与互动报告页。 |
| `frontend/app/classroom/[access_token]/page.tsx` | 免登录手机课堂投票/弹幕入口。                       |

### 组件

| 路径                           | 作用                                        | 当前审计状态               |
| ------------------------------ | ------------------------------------------- | -------------------------- |
| `components/session-provider/` | Session、CSRF 和角色路由边界。              | 历史基线。                 |
| `components/locale/`           | 中英界面切换与翻译表。                      | 历史基线。                 |
| `components/avatar/`           | 3D 预览和课堂 Avatar 状态。                 | 历史 Mock 验收。           |
| `components/debate/setup/`     | 辩论草稿和参与者选择。                      | Wave 2 历史通过。          |
| `components/debate/stage/`     | 教师课堂舞台、播放控制、事件恢复和 Replay。 | 最新增量未完成 Full 审计。 |
| `components/interaction/`      | 教师互动面板、二维码和匿名手机表单。        | M13 未完成 Full 审计。     |
| `components/report/`           | Maya 报告状态、生成、Revision 和下载。      | M14 未完成 Full 审计。     |
| `components/history/`          | 发言、来源、票数、弹幕和报告历史。          | M15 未完成 Full 审计。     |
| `components/translation/`      | 按需测试翻译按钮与状态。                    | M15 未完成 Full 审计。     |
| `components/wave3/`            | 教师 Wave 3 页面组合层。                    | 页面整合未完成 Full 审计。 |

### API

| 路径                           | 作用                                                                   |
| ------------------------------ | ---------------------------------------------------------------------- |
| `frontend/lib/api/generated/`  | 根据冻结 OpenAPI 生成的 TypeScript Schema/Client，不手工维护业务类型。 |
| `frontend/lib/api/platform.ts` | 页面使用的 Provider-neutral API 封装。                                 |
| `frontend/lib/i18n.ts`         | 平台静态界面文案和业务提示翻译。                                       |

### 测试

`frontend/tests/` 使用 Vitest 与 Testing Library。Wave 3 重点文件包括：

- `wave3-interaction.test.tsx`；
- `wave3-report.test.tsx`；
- `wave3-history-translation.test.tsx`；
- `wave3-playback-controls.test.tsx`；
- `wave2-playback.test.tsx`（仍承载大量播放恢复回归）。

## `contracts/`

| 路径                               | 作用                                             |
| ---------------------------------- | ------------------------------------------------ |
| `openapi-v0.1.yaml`                | 前后端唯一 HTTP 合同。                           |
| `openapi-v0.1.sha256`              | 冻结 OpenAPI 内容校验值。                        |
| `response-contract-allowlist.json` | 显式响应差异白名单；不能作为绕过合同的万能开关。 |
| `route-surface-placeholders.json`  | 已实现、缺失和基础设施额外路由的分类。           |
| `ws-events.v1.schema.json`         | 封闭的 WebSocket 事件联合 Schema。               |
| `fixtures/`                        | WS 正例/反例和契约测试输入。                     |

## `scripts/`

| 路径                           | 作用                                                  |
| ------------------------------ | ----------------------------------------------------- |
| `bootstrap_local_demo.py`      | 在空运行目录初始化预置课程、用户和 Demo 基础数据。    |
| `test_bootstrap_local_demo.py` | 验证初始化的安全性和可重复性。                        |
| `test_wave1_migration.py`      | Wave 1 populated 迁移保留性。                         |
| `test_wave2_migration.py`      | Wave 2 populated 迁移保留性。                         |
| `test_wave3_migration.py`      | 0007 fresh/repeat/downgrade/re-upgrade/FK/指纹验证。  |
| `check_frozen_openapi.mjs`     | 检查冻结 OpenAPI 和 Hash。                            |
| `compare_route_surface.mjs`    | 对比 FastAPI 实际路由与冻结合同。                     |
| `generate_ws_schema.mjs`       | 生成/同步 WS Schema。                                 |
| `generate_ws_fixtures.mjs`     | 生成 WS 测试 Fixture。                                |
| `check_repo_boundary.mjs`      | 检查 `.env`、运行数据和未授权私密文件是否进入当前树。 |
| `test_repo_boundary.mjs`       | 使用临时探针验证边界检查不会漏报。                    |

## `config/`

| 路径                          | 作用                             |
| ----------------------------- | -------------------------------- |
| `repository-data-policy.json` | 当前团队私库的精确数据保留策略。 |

## `backend/config/`

| 路径                                | 作用                                     |
| ----------------------------------- | ---------------------------------------- |
| `demo-accounts/accounts.private.md` | 用户明确要求保留的 Demo 账号与密码目录。 |
| `demo_users.yaml`                   | 旧 Demo 账号兼容配置。                   |

这些文件只用于私有团队 Demo，不得由普通 API、前端 Bundle、错误响应或日志返回密码。

## `private-inputs/voice/`

保留用户明确批准的本人音色样本，用于未来独立语音 Gate。它不是运行数据库，也不能被 Web 服务作为公开静态资源暴露。

## 不应出现在当前仓库树中的内容

- `.env` 和真实 Provider Key；
- `data/`、`backend/data/` 运行数据库；
- SQLite WAL/SHM；
- 已创建的 Agent、Debate、Turn、投票、弹幕、报告和翻译运行记录；
- 生成的课堂音频、临时文件和锁；
- `node_modules`、`.next`、`.venv`、缓存、Coverage；
- 旧 `archive/` 和 `outputs/` 交接产物。

新成员从 `README.md` 开始；开发前读 `Project.md`；接手未完成工作时再读 `docs/PROJECT_STATUS.md` 与对应 Gate Packet。
