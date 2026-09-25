# Mayaform

Mayaform 是面向文化互学的 RAG 教学平台。学生编写 Agent 人设和知识文档，教师组织 **2–5 位 Agent、固定四轮**中英文辩论。前三轮在 Preview 准备并保存，第四轮结合课堂消息现场生成；课堂结束后查看 Evaluation 和 Report。

## 当前功能

- **账号**：学生自由注册，填写用户名、至少五字符的密码和小组名；同一课程内的同名小组自动归并。用户名不区分大小写，并发重名注册只提示冲突，不改变已有登录。
- **教师 Accounts**：查看成员、修改显示名、调组、停用/恢复、重置密码。私有 Demo 目录账号由目录管理，自注册账号可在页面编辑。
- **教师进入小组**：在 Accounts 的 Groups 中点击 **Enter**，以教师身份使用完整学生工作区，包括创建、编辑和删除；使用 **Homeward** 返回 Accounts。访问关系独立保存，重启同步 Demo 目录不会清除它。已发布历史及费用授权规则仍适用。
- **工作区**：老师、学生和扫码互动页面统一采用系统字体、灰白表面与登录页的暖黄色，保留原版 Logo；Chat 和 Immerse 共用按钮与配色，支持窄屏与键盘操作。登录页不变，移除解释性介绍，保留权限、费用和错误提示。
- **Chat**：老师和学生选择本课程已发布 Agent 进行私人文字对话，显示 3D 形象；历史、引用与绑定版本由服务器保存。其他用户（包括老师）不能读取个人会话。
- **Live**：老师进入 Immerse 后，学生的 Live 入口亮起，同步公开发言、人物和已有音频。学生不获得控制权，观看不额外调用模型；退出或租约过期关闭。
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

**New / Back / Done** 统一在侧栏，只显示当前可用的操作；主内容区不重复放创建、返回和提交按钮。Chats 只有 New 和输入框内的发送箭头；全屏 Immerse 保留自己的控制键。

1. **准备 Agent**：学生进入 Workspace，New 创建 Agent；自由编写中英文 AGENT.md（最多 12,000 字符）、启用 RAG（每文件最多 100,000 字符），配置形象及声音，侧栏 **Done** 保存并发布。不再需要 Persona、Compile / Confirm 或 Test Chat；用 **Chats** 与已发布 Agent 多轮对话。点击 Agent 直接检查当前版本；此处 **New** 创建下一版，已有草稿则直接打开。Workspace 的 **Delete** 统一移除师生入口，任何 Debate 引用都会阻止删除，已有单聊保留只读历史。
2. **创建辩论**：教师进入 **Debates → New**，填写 Topic / Background，选择 2–5 位 Agent、顺序和立场，确认 Ruleset 的语言及内容后点击 **Done**。
3. **准备前三轮**：Preview 展示 Background 和各轮发言。固定流程为 **Opening → Discussion → Response → Conclusion**；前三轮保存正文与音频，后续发言能看到此前成功完成的发言，包括同轮上下文。
4. **进入课堂**：准备就绪后点击 **Immerse**。操作键独立放在屏幕最右侧；**Transcript** 展开发言记录侧栏，保留 Public Debate、课堂状态和 Check RAG。**Interact / Hide** 显示或收起消息二维码；Hide 不关闭已有扫码入口。第四轮冻结可用消息后生成回应。
5. **查看结果**：**Check RAG** 查看证据。课堂播放完成后使用 **Conclude** 查看 Evaluation 和 Report；报告提供版本/历史、Review 和 Regenerate。

证据支持等级为直接支持 **+5**、间接支持 **+2**、No match **+0**，不等于事实真伪评分。发言篇幅由 Prompt 指导，不因长度自动截断、补齐或拒收。

## 课堂恢复与清理

| 操作                        | 行为                                                                        |
| --------------------------- | --------------------------------------------------------------------------- |
| **Rebirth**                 | 已完成课堂保留前三轮，清理第四轮及该次课堂/报告结果，回到可继续准备的状态。 |
| **Devocalize / Revocalize** | 移除或恢复该场音频，保留正文和来源。                                        |
| **Delete**                  | 删除目标辩论及相关课堂记录，不删除独立编写的 Agent 和知识库。               |

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

后端启动时自动迁移，`0030` 增加私人聊天、加密配置和 Live 租约。若旧用户名或小组名规范化后冲突，迁移会停止，不会静默合并身份。

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

首次启用还需要配置本地凭据、区域、`LLM_MODEL` 和已审核的 Provider policy，并完成教师披露确认；详见 [真实服务配置](docs/REAL_PROVIDER_SETUP.md)。仅修改上述选择项或填写 API Key 不足以完成配置。聊天、辩论和报告共用 `LLM_MODEL`，改这一项即可换模型。

教师首页的 Components 可切换 LLM、Embedding、Report 的 Real/Mock；缺 Key 时弹窗填写，服务器加密保存，不回传 Key。右上角仅一个 **Check**，只检查尚未 Ready 或已更改的能力；真实检测先确认本批最多请求数，失败即停止。改模式仅使该项检查失效，改 Key 使全部检查失效。活跃生成期间禁止切换，网页配置重启后保留。Mock 与真实 Embedding 快照不混用。

老师和学生均可在 **Chat** 选择已有已发布 Agent；会话与引用仅本人可读，重新进入保留历史。老师进入 Immerse 后，学生 **Live** 亮起，共享人物、当前发言和公开发言记录；不投屏，也不重复生成内容。界面没有 Refresh 按钮；列表仍自动读取最新状态，断线可重新进入。

TTS 与 Voice 默认仍是 mock。需要语音克隆或聊天朗读时，把 `TTS_PROVIDER` 和 `VOICE_PROVIDER` 设为 `dashscope`，它们与 LLM 共用 `DASHSCOPE_API_KEY`，没有单独的语音密钥。轮换密钥只改这一项并重启后端，工作区、区域和 `SESSION_SECRET` 保持不变；已克隆的音色属于工作区，不随密钥改变。苏格拉底、柏拉图、老子不能改资料，要用 `BASELINE_DEFAULT_VOICES` 指定音色档案 id，不写进代码；省略的角色使用 `FALLBACK_VOICE_PROFILE_ID`。柏拉图的预置音色 Eldric Sage 用 `scripts/seed_preset_voice.py` 写入，再把打印的档案 id 配成 `plato=<id>`。步骤见 [真实服务配置](docs/REAL_PROVIDER_SETUP.md)。教师首页 Components 仍把 TTS 与 Voice 标为 Deferred，不能在网页上切换。面对面实时语音另行接百炼北京，按用户要求最后实施，当前 Chat 不宣称支持实时语音。详见 [接入边界](docs/adr/ADR-008-agent-chat-live-provider-controls.md)。

## 开发与验证

```sh
pnpm check
```

代码检查与真实课堂验收分别记录。当前能力、验证结果和未完成项以 [PROJECT](docs/PROJECT.md) 为准；自动测试通过不代表真实 RAG 内容、课堂体验或所有服务已验收。

[工作约定](AGENTS.md) · [架构说明](docs/ARCHITECTURE.md) · [接口契约](contracts/openapi-v0.1.yaml)

`.env`、私有账号目录、运行数据库、Provider 私有配置和生成音频不提交 Git。日常备份应包含本地运行数据及必要的私有配置，并自行安全保管。
