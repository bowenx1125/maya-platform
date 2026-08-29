# Maya Platform 私有仓库保存范围

本仓库是 Maya Platform 的团队私有开发仓库。当前树只保存可继续开发和审计的源代码、契约、测试、文档，以及用户明确要求保留的 Demo 账号配置。

## 当前允许保存

- Backend、Frontend、迁移、脚本和 Docker 配置；
- OpenAPI、WebSocket Schema、生成 Client 和测试 Fixture；
- 当前 `README.md`、`Project.md`、Gate 文档、状态报告和 `开发文档.xlsx`；
- 原始业务需求与手工测试资料；
- `backend/config/demo-accounts/accounts.private.md`；
- `backend/config/demo_users.yaml`。

上述两份账号文件可以包含 Demo 用户名和密码，因为仓库保持私有且用于团队协作。密码不得进入普通 API、WebSocket、前端 Bundle、生成 Client、日志、错误信息、截图或公开文档。

## 当前禁止保存

- `.env`、API Key、Session Secret 和真实 Provider 凭据；
- `data/`、`backend/data/`、SQLite、WAL、SHM、数据库备份；
- 已创建的 Agent、AgentVersion、Debate、Turn、Interaction、Vote、Barrage、Report、Translation 等运行记录；
- 运行时知识文件、发布快照、生成的课堂音频、临时文件和锁；
- `private-inputs/` 下的个人音频或本地诊断脚本；
- `node_modules`、`.next`、`.venv`、Coverage 和缓存；
- `archive/`、`outputs/` 和重复开发表格。

## 本地运行数据

开发者从 `.env.example` 创建本地 `.env`，在忽略的 `data/` 目录中生成数据库和运行文件。创建 Agent 或 Debate 不应改变 Git 工作树。

## 历史说明

清理前的 Handoff Commit 仍存在于 Git 历史中；本次工作没有重写历史或强制推送。当前分支和后续主分支以“源代码 + Demo 账号配置”为干净基线。若以后需要彻底清除历史对象，需要单独执行历史重写与协作者重新克隆流程。

## 公开前检查

仓库若要公开，必须先移除两份 Demo 账号文件、轮换相关密码，并重新执行隐私、第三方素材和真实 Provider 配置审计。
