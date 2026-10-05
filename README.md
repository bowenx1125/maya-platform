# Mayaform

Mayaform 是面向文化互学的 RAG 教学平台。学生编写 Agent 人设和知识文档，教师组织 **2–5 位 Agent、固定四轮**中英文辩论。前三轮在 Preview 准备并保存，第四轮结合课堂消息现场生成；课堂结束后查看 Evaluation 和 Report。

## 当前功能

- **账号**：学生自由注册，填写用户名、至少五字符的密码和小组名；同一课程内的同名小组自动归并。用户名不区分大小写，并发重名注册只提示冲突，不改变已有登录。
- **教师 Accounts**：查看成员、修改显示名、调组、停用/恢复、重置密码。私有 Demo 目录账号由目录管理，自注册账号可在页面编辑。
- **教师进入小组**：在 Accounts 的 Groups 中点击 **Enter**，以教师身份使用完整学生工作区，包括创建、编辑和删除；使用 **Homeward** 返回 Accounts。访问关系独立保存，重启同步 Demo 目录不会清除它。已发布历史及费用授权规则仍适用。
- **工作区**：老师、学生和扫码互动页面统一采用系统字体、灰白表面与登录页的暖黄色，保留原版 Logo；Chat 和 Immerse 共用按钮与配色，支持窄屏与键盘操作。登录页不变，移除解释性介绍，保留权限、费用和错误提示。
- **Chats**：Agent、Team 和 Maya Team 使用同一通用聊天界面，文字回复流式显示；保留圆角悬浮输入框与聊天历史，不展示 3D 模型或播放语音。历史、引用与版本由服务器保存，Private 仅本人可读，Public 按实际权限读取；形象在 Workspace 中编辑。
- **Live**：老师进入 Immerse 后，学生的 Live 入口亮起，同步公开发言、人物和已有音频。学生不获得控制权，观看不额外调用模型；退出或租约过期关闭。Live 画面下方的 Interact 直接打开扫码同款填写页面，弹幕不限发送次数，Final 前自动停止收集。
- **声音**：Voices 点击文件名可直接改名，Enter／移开焦点保存，Escape 取消；不显示内部 ID。上传页不选择语言，试听默认英语，辩论朗读跟随 Ruleset。克隆音色属于上传者；同组其他学生和教师不能查看、试听、绑定或删除该音色。
- **3D 课堂**：2–5 位国风人物围绕圆桌站立，气泡和 Transcript 随音频显示；音频失败时仍保留完整文字。实验性高斯院落需要额外的本地生成资源，不是默认课堂依赖。
- **教学内容**：Topic 与可选 Background 分开保存；中英文 Markdown Ruleset 可编辑，创建辩论时冻结；发言身份和指代要求也在 Ruleset 内，可修改或删除。Agent.md 和 RAG 不设人为编写字数配额。

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

**New / Back / Done** 沿用当前页面的统一操作，只显示当前可用的操作。Chats 保持通用聊天交互；全屏 Immerse 保留自己的控制键。

1. **准备 Agent**：学生进入 Workspace，New 创建 Agent；自由编写中英文 AGENT.md、启用 RAG，配置形象及声音，AGENT.md 首行 `# 名字` 会在保存时同步当前 Agent 名称；**Done** 保存并发布。不再需要 Persona、Compile / Confirm 或 Test Chat；用 **Chats** 与已发布 Agent 多轮对话。点击 Agent 检查当前版本；初始 Draft 和已有 Published 都使用 **New** 打开草稿编辑（需要时创建下一版），由 **Done** 保存并发布。每个 Workspace 内名称不能重复（忽略大小写、首尾空格及全半角差异）；重名时请换名或先删除重复 Agent。下一版 Draft 可重新选择本人已就绪音色，或切回平台默认音色，旧版本保持不变。Workspace 的 **Delete** 统一移除师生入口，任何 Debate 引用都会阻止删除，已有单聊保留只读历史。
2. **创建辩论**：教师进入 **Debates → New**，填写 Topic / Background，选择 2–5 位 Agent、顺序和立场，确认 Ruleset 的语言及内容后点击 **Done**。
3. **准备前三轮**：点击 Debates 列表中的辩论卡片进入预览，查看 Background 和各轮发言；页面保留议题标题，不显示额外的“Preview”标题。固定流程为 **Opening → Discussion → Response → Conclusion**；前三轮保存正文及可用音频；自定义音色不可用时使用平台默认音色，默认音色也不可用时保留文字发布与手动 Next，后续发言能看到此前成功完成的发言，包括同轮上下文。
4. **进入课堂**：准备就绪后点击 **Immerse**。操作键独立放在屏幕最右侧；**Transcript** 展开发言记录侧栏，保留 Public Debate、课堂状态和 Check RAG。**Interact / Hide** 显示或收起消息二维码；Hide 不关闭已有扫码入口。进入 Final 时自动停止接收新弹幕，不设手动暂停按钮。第四轮冻结可用消息后生成回应，并在 Transcript 的回复段落旁展示对应匿名留言；弹幕不是逐条即时回复。
5. **查看结果**：**Check RAG** 查看证据。课堂播放完成后使用 **Conclude** 查看 Evaluation 和 Report；报告提供版本/历史、Review 和 Regenerate。

Report 不因供应商返回的 model/object 标识不同而拒收；usage 缺失或不一致也不阻止生成，仍校验报告正文与完成状态。

证据支持等级为直接支持 **+5**、间接支持 **+2**、No match **+0**；缺少等级时也显示 No match，不另列 unscored 计数，不等于事实真伪评分。发言篇幅由 Prompt 指导，不因长度自动截断、补齐或拒收。

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

后端启动时自动迁移，当前代码版本为 `0053_user_profile`；`0030` 增加私人聊天、加密配置和 Live 租约，`0031` 增加 Agent 删除标记，`0032` 移除恢复输入大小限制，`0033` 移除预算与调用序号上限并保留历史账本。若旧用户名或小组名规范化后冲突，迁移会停止，不会静默合并身份。

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

Provider 模式、API Key 和连通性检查由维护层管理，教师首页不提供 Components 控件。现有配置和调用账本继续保留，Mock 与真实 Embedding 快照不混用；具体资料外发仍需按当前身份、用途和准确清单完成必要的教师披露确认。

**Chats → New** 支持 Agent、Team 和 Maya Team。教师本人创建的课程内个人 Public Team 保存后自动进入 Maya Team；学生选择教师命名的 Team，再选择 Private/Public，即可开始自己的会话。Private 不进入教师查询，Public 正式测评可以按授权汇总；普通 Public 聊天不自动进入诊断报告。重新进入保留历史，Chats 只输出文字。老师进入 Immerse 后，学生 **Live** 亮起，共享人物、当前发言和公开发言记录；不投屏，也不重复生成内容。列表自动更新，断线可重新进入。

真实 Maya Team 首次调用前，教师从首页个人 Agents 区域的披露入口，确认该 Team 当前版本的回复与检索资源。发布不替代这项数据外发授权，课程通用确认也不替代具体 Team 资源确认。缺少授权时请求不会发出；确认后由学生明确发送新消息，旧失败请求不会自动重发。

TTS 与 Voice 默认仍是 mock。需要语音克隆或课堂语音播放时，把 `TTS_PROVIDER` 和 `VOICE_PROVIDER` 设为 `dashscope`，它们与 LLM 共用 `DASHSCOPE_API_KEY`，没有单独的语音密钥。轮换密钥只改这一项并重启后端，工作区、区域和 `SESSION_SECRET` 保持不变；已克隆的音色属于工作区，不随密钥改变。苏格拉底、柏拉图、老子不能改资料，要用 `BASELINE_DEFAULT_VOICES` 指定音色档案 id，不写进代码；省略的角色使用 `FALLBACK_VOICE_PROFILE_ID`。步骤见 [真实服务配置](docs/REAL_PROVIDER_SETUP.md)。TTS / Voice 由本地环境配置管理，不能在网页上切换；Real 表示已选择真实适配器，不等于音色已准备好或供应商请求已验收。面对面实时语音另行接百炼北京，按用户要求最后实施，当前 Chat 不宣称支持实时语音。详见 [接入边界](docs/adr/ADR-008-agent-chat-live-provider-controls.md)。

后端不再按请求次数、Token 数或金额预算阻止调用，也不向 LLM / Report 发送固定输出 Token 上限。实际用量、费用、权限、披露确认和去重仍保留；供应商自身的容量限制仍适用。

## 开发与验证

工作区和课堂操作支持中英文悬停、键盘焦点及触控提示；知识上传仍限 Markdown，PDF/Word 导入尚未实现。

```sh
pnpm check
```

代码检查与真实课堂验收分别记录。当前能力、验证结果和未完成项以 [PROJECT](docs/PROJECT.md) 为准；自动测试通过不代表真实 RAG 内容、课堂体验或所有服务已验收。

[工作约定](AGENTS.md) · [架构说明](docs/ARCHITECTURE.md) · [接口契约](contracts/openapi-v0.1.yaml)

`.env`、私有账号目录、运行数据库、Provider 私有配置和生成音频不提交 Git。日常备份应包含本地运行数据及必要的私有配置，并自行安全保管。

署名 **Work With Bowen** 显示在 Logout 上方的分隔线上方。
Chats 仅生成文本，不再调用 TTS 或自动播放语音。
