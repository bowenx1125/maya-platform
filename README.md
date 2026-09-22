# Mayaform

Mayaform 是面向文化互学的 RAG 教学平台。学生编写 Agent 人设和知识文档，教师组织 **2–5 位 Agent、固定四轮**中英文辩论。前三轮在 Preview 准备并保存，第四轮结合课堂消息现场生成；课堂结束后查看 Evaluation 和 Report。

## 当前功能

- **账号**：学生自由注册，填写用户名、至少五字符的密码和小组名；同一课程内的同名小组自动归并。用户名不区分大小写，并发重名注册只提示冲突，不改变已有登录。
- **教师 Accounts**：查看成员、修改显示名、调组、停用/恢复、重置密码。私有 Demo 目录账号由目录管理，自注册账号可在页面编辑。
- **教师进入小组**：在 Accounts 的 Groups 中点击 **Enter**，以教师身份使用完整学生工作区，包括创建、编辑和删除；使用 **Homeward** 返回 Accounts。访问关系独立保存，重启同步 Demo 目录不会清除它。已发布历史及费用授权规则仍适用。
- **学生工作区**：首页、小组、Agent 创建/详情/编辑/版本、知识库、声音和扫码互动页面统一采用教师侧 Mayaform 的字体、白色卡片、浅黄色内容区和金色分隔线，并支持窄屏布局。功能按钮采用单词标签，页面不堆放解释性介绍。首页为 **Home**；列表仅保留 Agent 名称和状态，点击 Agent 后在 **Info → Edit** 修改 Description。教师使用 **Homeward** 返回 Accounts。
- **声音**：克隆音色属于上传者；同组其他学生和教师不能查看、试听、绑定或删除该音色。
- **3D 课堂**：2–5 位国风人物围绕圆桌站立，气泡和 Transcript 随音频显示；音频失败时仍保留完整文字。实验性高斯院落需要额外的本地生成资源，不是默认课堂依赖。
- **教学内容**：Topic 与可选 Background 分开保存；中英文 Markdown Ruleset 可编辑，创建辩论时冻结。Agent.md 的总编写预算为 12,000 字符。

当前产品范围是 **单课程本地 Demo**。无需邀请码；登录保留“用户名不存在”和“密码错误”的区分。多课程注册和公共部署尚不属于已验收范围。

## 首次启动

准备 **Docker Desktop、Git、Node.js 24.14 或更新的 24.x、pnpm 11.19.0 和 uv**，先启动 Docker Desktop：

```sh
git clone https://github.com/bowenx1125/maya-platform.git
cd maya-platform
pnpm install --frozen-lockfile
pnpm bootstrap:local
docker compose up -d --build --wait
```

Bootstrap 创建本地私有配置和 Demo 账号；已有配置不会被覆盖，`uv` 会准备后端 Python 环境。打开 [localhost:8080](http://localhost:8080)，可选择 Demo 身份，或点击 **Create an account** 自行注册。教师 Demo 身份为 **Maya**。

新安装默认使用 Mock，无需 API Key。已有环境升级时继续使用原来的 `.env` 配置。

## 一次课堂

1. **准备 Agent**：学生进入小组，创建 Agent，编写 AGENT.md，上传并启用知识文档；完成 Persona 的 **Compile / Confirm**，配置形象及声音，点击 **Publish** 发布。
2. **创建辩论**：教师进入 **Classroom → New**，填写 Topic / Background，选择 2–5 位 Agent、顺序和立场，确认 Ruleset 的语言及内容后点击 **Done**。
3. **准备前三轮**：Preview 展示 Background 和各轮发言。固定流程为 **Opening → Discussion → Response → Conclusion**；前三轮保存正文与音频，后续发言能看到此前成功完成的发言，包括同轮上下文。
4. **进入课堂**：准备就绪后点击 **Immerse**。用 **Next / Back** 操作课堂，**Interact / Hide** 显示或收起消息二维码；Hide 不关闭已有扫码入口。第四轮冻结可用消息后生成回应。
5. **查看结果**：**Check RAG** 查看证据。课堂播放完成后使用 **Conclude** 查看 Evaluation 和 Report；报告提供版本/历史、Review 和 Regenerate。

证据支持等级为直接支持 **+5**、间接支持 **+2**、No match **+0**，不等于事实真伪评分。发言篇幅由 Prompt 指导，不因长度自动截断、补齐或拒收。

## 课堂恢复与清理

| 操作                        | 行为                                                                             |
| --------------------------- | -------------------------------------------------------------------------------- |
| **Refresh**                 | 尝试恢复失败或停滞的准备任务，复用已有结果；不会盲目重复发送受理状态不明的请求。 |
| **Rebirth**                 | 已完成课堂保留前三轮，清理第四轮及该次课堂/报告结果，回到可继续准备的状态。      |
| **Devocalize / Revocalize** | 移除或恢复该场音频，保留正文和来源。                                             |
| **Destroy**                 | 删除目标辩论及相关课堂记录，不删除独立编写的 Agent 和知识库。                    |

使用真实服务时，明确恢复、重新生成或重开课堂可能产生新的费用；界面上的授权与费用检查仍有效。

## 日常维护

在仓库目录运行。普通启停保留 `data/`；更新前先处理自己的未提交代码，并备份运行数据。

| 操作           | 命令                                  |
| -------------- | ------------------------------------- |
| 启动           | `docker compose up -d --wait`         |
| 重启，配置不变 | `docker compose restart`              |
| 停止           | `docker compose stop`                 |
| 更新代码       | `git pull --ff-only`                  |
| 更新后重建     | `docker compose up -d --build --wait` |
| 查看状态       | `docker compose ps`                   |

后端启动时自动执行数据库迁移。账号集成包含 `0028`、`0029`；若旧数据的用户名或小组名规范化后发生冲突，迁移会停止，不会静默合并身份。

修改 `.env` 后执行 `docker compose up -d --wait` 以重新创建需要更新配置的容器。更换 Wi-Fi 后，可运行：

```sh
uv run --directory backend python ../scripts/refresh_classroom_address.py
docker compose up -d --wait
```

学生手机与教师电脑须在可互通的局域网内。课堂地址须与访问端口匹配，否则可能影响二维码和保存操作。

## Mock 与真实服务

Debate LLM、Embedding 和 Report 独立配置。启用真实适配器的选择项为：

```dotenv
LLM_PROVIDER=dashscope
EMBEDDING_PROVIDER=dashscope
MAYA_REPORT_PROVIDER=dashscope
```

首次启用还需要配置本地凭据、区域、价格卡和已审核的 Provider policy，并完成教师披露确认；详见 [真实服务配置](docs/REAL_PROVIDER_SETUP.md)。仅修改上述选择项或填写 API Key 不足以完成配置。

切回 Mock 时将对应值改为 `mock`。修改后执行 `docker compose up -d --wait`。Mock 与真实 Embedding 快照保持各自身份，切换后应按目标模式重新发布知识快照。教师首页的 Providers Composition 显示实际模式；当前交付环境的 TTS / Voice 保持 Mock。

## 开发与验证

```sh
pnpm check
```

代码检查与真实课堂验收分别记录。当前能力、验证结果和未完成项以 [PROJECT](docs/PROJECT.md) 为准；自动测试通过不代表真实 RAG 内容、课堂体验或所有服务已验收。

[工作约定](AGENTS.md) · [架构说明](docs/ARCHITECTURE.md) · [接口契约](contracts/openapi-v0.1.yaml)

`.env`、私有账号目录、运行数据库、Provider 私有配置和生成音频不提交 Git。日常备份应包含本地运行数据及必要的私有配置，并自行安全保管。
