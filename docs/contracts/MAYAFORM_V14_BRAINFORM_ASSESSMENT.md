# MayaForm v1.4 adopted Brainform and assessment contract

Product requirements adopted by the user on 2026-10-03 from the Resume v2 attachment.
This is the canonical product contract, not evidence of implementation or an
instruction to trust historical test results. Engineering execution and progress
remain governed by AGENTS.md and PROJECT.md. Conflicting older supplement decisions
are superseded; committed K3-A and unrelated authorized changes remain preserved.

The later [Tool and target-resource correction](MAYAFORM_V14_TOOL_RESOURCE_AUTHORIZATION.md)
supersedes the two-class clauses below: Public/Student/Teacher are the current
classes; formal edit rights are restricted execution grants, not actor/Team type
bans. Safe reads follow the target attempt even from a different Agent/Chat.

## 1. 必须替代的旧条款

| 旧条款                                     | 本次最终决定                                                                              |
| ------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Knowledge 是独立的原始文件/资产主入口      | 主导航改为 **Brainform**，同页直接展示 RAG、Knowledge、Memory                             |
| 三类内容先选分类再进入列表                 | 打开 Brainform 后三块内容都可见，不多加分类落地页                                         |
| New 随当前分类改变含义                     | 在 Brainform 上，左侧 **New 始终只新增 RAG Markdown 资料**                                |
| 文件旁“编辑＋更多”                         | 常用动作改为 **编辑＋查看** 两个符号按钮；不以“更多”菜单承载必需动作                      |
| 一个 Agent 对外管理多套派生 Knowledge      | 一个 Agent 一个当前 Knowledge 入口/逻辑文档；多种内容在同一 Markdown 中分节               |
| Knowledge 再手工新建 Concept/Question/Note | 本页不提供这些新增流程；编辑同一份 Markdown 即可                                          |
| 引用的 Knowledge 被复制给使用 Agent        | 引用同一 canonical Knowledge，查看/编辑跳转到真实来源，权限不被跳转放大                   |
| RAG 改动后只有手动重生成                   | 成功修改已绑定 RAG 自动更新关联 Knowledge；仍保留明确的手动重生成 `↻`                     |
| AI 不覆盖人工编辑 head                     | **RAG 更新或手动 `↻` 后，新生成结果默认覆盖当前人工修改；旧版仍留存**                     |
| Memory 完全没有入口                        | 增加轻量 Memory 入口；点击 Agent 的进入符号跳 Chats，自动询问当前授权记忆，不做记忆编辑器 |
| Chats 旧文档仍描述自动 TTS／语音输出       | 本轮 Chats 只输出文字；不恢复语音接线，不删除其他授权模块的 Voice 工作                    |
| 测评可以边提示边答题                       | **测评回合内不提供答案、解题提示或教学解释，只收集回答、选择后续题并记录**                |
| New/刷新可以重置未结束测评                 | 一个回合必须完成或明确放弃才能开始新回合；暂停只能继续原回合                              |
| 测评过程中可以自由聊其他事                 | 本次测评内只受理作答、已有作答记录和进度查询、暂停/继续/完成/放弃；结束后恢复普通交流     |

上表是明确的产品变更，不得以旧测试保护旧行为。修改冲突测试时记录替代关系，并补新行为的正反测试，不能只删断言。

恢复报告中的“Sources／Concepts／Questions／Notes 四类主 UI”“不新增 Memory 页面”是历史目标，不能据此漏掉 Brainform。同一 Markdown 可以继续承载这些内容，但不再要求用户逐个进入四种管理模块。Memory 是 Brainform 同页的聊天快捷入口，不是新增一套记忆编辑后台或 Insights dashboard。

旧“两种教学模式”的未完成草案不构成新增产品决定：本次测评回合统一使用第 8 节无提示协议；既有非测评的正常交流继续保留，不增设要求老师额外选择的模式面板。

## 2. Brainform：一个页面，三块直接可操作的内容

侧栏原 Knowledge 入口显示为 Brainform。一次点击进入后，同一页面呈现 RAG、Knowledge、Memory 的内容列表，不做三个必须再点击一次才显示内容的分类卡片，也不新增 dashboard。

桌面采用现有布局中最清楚的三块区域，窄屏自然纵向排列。共享当前课程与身份上下文；切课程、切账号、切选择时隔离迟到响应。不要增加三套不同的文件库。

页面示意中的方括号仅代表符号按钮，实际用现有统一 SVG 图标，不用 emoji 代替组件：

```text
Brainform

RAG
Lecture 01.md                         [编辑] [查看]
Lecture 02.md                         [编辑] [查看]

Knowledge
Maya                                  [编辑] [查看] [↻]
Jade → Maya                           [编辑*] [查看] [↻*]

Memory
Bowen                                 [进入 Chats]
Kaikai                                [进入 Chats]
```

`*` 仅在当前用户对真实目标拥有相应权限时出现。引用关系必要时用简短来源名称说明，不堆技术字段。

最短路径要求：打开 Brainform 后，点击 RAG 文件名直接编辑；行尾查看符号打开渲染视图，编辑符号打开编辑器。Knowledge 的查看符号直接进入该 Agent 对应的完整 Knowledge，编辑符号直接打开同文档编辑器。Memory 的进入符号直接跳到正确 Chats 上下文。

左侧 New 在 Brainform 主页面及其编辑/查看子状态都始终指向 RAG 新增；它不创建 Knowledge、Memory 或 Chat。有未保存内容时沿用既有防丢稿机制，不静默丢失输入。Chats 的 New 仍保留 Agent / Team / Maya Team 三种方式，不被本页 New 改动影响。

用铅笔表示编辑，眼睛或现有查看图标表示查看，箭头表示进入，循环箭头表示重新生成。常用动作不显示长文字按钮；保留 accessible name、焦点、键盘与触屏支持。保持暖纸视觉、统一间距和现有 UI/UX Pro Max 规范，不加常驻 Ready/Reviewed/Outdated/Published 等标签。

## 3. RAG：只处理 Markdown 上传与编辑

首期输入文件全部是 Markdown，PDF/PPT 转 Markdown 已由外部完成。本切片不开发 PDF/PPT/DOCX 转换、OCR 或原件编辑，不删除其他已有业务仍需要的历史转换能力。

RAG 支持新增、直接编辑、查看渲染内容；已有删除、解绑、下载能力如仍在用，应保留兼容入口，不因移除“更多”常用按钮而破坏旧功能。

保存后保留稳定资料 ID，产生新内容版本，并更新授权检索。自动生成不能覆盖 RAG 原文。改名只改变名称，不冒充内容修改或触发不必要模型请求；知识内容或相关资料绑定发生有效变化时，按第 6 节传播更新。

上传文件可立即出现在列表，但读取、索引或生成尚未完成时要有真实 loading，不能把“文件已保存”说成“检索与 Knowledge 已全部更新”。失败时保留文件和输入，说明实际失败步骤与可执行的恢复动作。

## 4. Knowledge：一个 Agent 一个逻辑文档，Markdown 是编辑与阅读主体

### 4.1 范围与入口

一个 Agent 最多有一个当前直接关联的 Knowledge 入口，可指向自己生成的 canonical 文档，也可指向其他 Agent 的同一份文档。一个文档可以包含多个概念、图、问题、Rubric、例子、笔记与其他有标题的内容，不是一份文档只能写一种东西。

一个文档有多个历史版本不违反“一份 Knowledge”。旧 Team 已绑定多个合法 Set 的运行兼容性仍保留；本次约束的是 Agent 的简洁管理入口，不强行把所有 Team 改成只可使用一个来源。

有知识的判断直接查持久资源和 read 权限：当前 Agent 有可读 canonical 文档或有效引用则显示。只有 RAG、没有派生产物且没有生成任务的 Agent 不显示在 Knowledge 列表。首次生成中的 Agent 临时显示 loading；首次失败无产物时保留这次真实失败与恢复入口，不能无声消失或一直转圈。不要调用 Planner 猜哪些 Agent“算有知识”。

Brainform 不增加 Knowledge 的 New、Add Concept、Add Question、Add Note。首次 Knowledge 复用已经实现的显式生成意图与 Agent 工作台 Done 流程，或由已有授权的 Agent 工具任务创建；保留现有 Create AI Knowledge 能力，但不要将它接到 Brainform 左侧 New，也不要再造一个 Knowledge 新建向导。

首次生成和后续更新分开：已有生成关系的 Knowledge 随其 RAG 有效修改自动更新；没有生成意图或关系的普通 Agent，不因随意上传一份 Markdown 就自动备课。不恢复职责 Planner／capability classifier，不按名字 Maya 猜职责。可从既有 Agent 工作台的明确生成入口发起首轮，普通 New Agent 的 Done 保持其现有语义。

### 4.2 Markdown 内容与渲染

用一个连续的 Markdown 阅读页面呈现完整 Knowledge，允许普通标题、列表、表格、公式和代码块。不是进入后再打开多层 Concepts/Questions/Notes 分类。

可采用以下生成模板，但不是手工文档必须满足的全部章节：

```markdown
# Computer Vision · Week 3

## Concepts

……

## Graph

……图的声明或 Mermaid 代码块……

## Questions

### Q1

题目……

#### Rubric

评估依据……

## Notes

……
```

Graph 仅安全渲染与查看，不做拖拽连线/图布局编辑器。内容可以是知识图谱、概念分解树或显式教学分析步骤，不要求或展示模型隐藏推理。新增合法标题自动作为普通 Markdown 呈现，不为每种内容另造页面。

点击编辑后修改同一 Markdown，保存一次自动产生并启用下一版本。标题点击改名仍为行内编辑，无改名说明或确认弹窗；正文编辑和名称编辑使用正确的稳定 ID 与并发控制。

Markdown 不执行脚本、任意 HTML 或外部代码。图语法无法渲染时显示安全原文和局部原因，不因一块图有误拒绝保存整个合法文档。正常 Markdown 没有某个教学章节也可保存，不新增 AI 审核、固定字数、内容评分或 Persona 编译门槛。

### 4.3 复用旧结构化资产，不造两份可以独立变化的真相

优先复用已实现的 Set/Asset/Version、来源收据、Question/Rubric ID、生成任务与 ACL。

对新结构，以版本化 Knowledge Markdown 为作者内容的权威来源；检索切片、图关系、问题与 Rubric 的可执行投影都明确对应某一文档版本和段落，不能后台各改一份。可复用旧表作为投影和历史证据，不要求物理上只剩一张表。

生成格式提供可稳定识别的内容边界，内部 ID/映射由系统维护；用户不必手填 UUID。保存普通 Markdown 不因无法结构化成测评题而失败；未能解析成可执行题的段落可查看/检索，但不能悄悄沿用错误题号、虚构 Rubric 或冒充可评分问题。需要评分时返回准确的“没有可用题目/评分依据”结果并保留可继续路径，不让 Chat 永久失效。

旧的多资产/多 Set 通过可追溯映射展示为同一逻辑文档或来源引用，保留旧 ID、版本和证据，不破坏历史 Chat。不能为凑成一个文档合并本来互不授权的 Private 资源。旧数据迁移先在副本验证，再按已有正式操作授权执行。

完整 Markdown 只交给有权读取完整内容的人。学生对自己有完整 read/edit 权的私人练习文档可以正常查看；教师课程题库、受限 Rubric 和当前测评的学生发言则采用相应授权投影。不要把“学生看不到教师内部答案”泛化成“学生永远不能看自己写的题目答案”。

隐藏 Rubric/答案不能先整份下发浏览器再用 CSS 折叠，也不能只依赖名为 Rubric 的 Markdown 标题遮挡。内容投影和题目/Rubric 边界必须与真实版本、来源和用途对应；历史只读、公开调用与完整源文件阅读权限继续分开。

## 5. 引用其他 Agent 的 Knowledge：跳转同一对象，不提升权限

如果 Jade 引用了 Maya 的 Knowledge，点击 Jade 右侧查看/编辑后解析同一个 canonical Knowledge ID，直接进入 Maya 的那一份，不复制、不 fork、不因跳转创建新版本。

“跳转到来源”只解决编辑错对象的问题，不代表任何人都有编辑权。能读不能改时只显示查看；不可读时不泄漏来源名称、正文或历史。维护层保存可验证的引用，避免循环指向和丢失目标，不让用户面对一串互相跳转的页面。

同一个 canonical 文档被多个 Agent/Team 使用时只更新一次，引用方看到同一新版本。保存后继承当前真实 ACL，不因生成者是教师就给学生教师权限。

运行继续遵守：当前成员自有已授权 RAG + 当前成员引用的已授权 Knowledge + 当前 Team 的已授权共享 Knowledge。去重按稳定资源身份处理；不得覆盖旧 Agent RAG，也不得合并其他成员的私人资料。本期不新增内容矛盾裁决或来源可信度打分系统。

## 6. 自动更新与手动重新生成：两种都保留

### 6.1 自动触发

用户成功保存一个已绑定 RAG 的有效内容修改后，自动为真正依赖它、且已有明确生成关系的 Knowledge 创建或更新持久生成任务。资料绑定的相关增删按同样原则处理。没有依赖关系的新上传文件不触发全站 Agent 备课。

触发依据是保存事件、内容版本及已存在的来源依赖，不是 AI 对 Agent.md 的职责判断。任务使用实际生成 Agent 的配置和最新合法资料；先更新本次需要的 RAG 读取/索引，再生成。

来源修改不等于任意目标的写入授权或无限消费许可。每个自动任务沿用其有效的生成授权主体和资源范围，重新核查来源 read、目标 edit、Provider 使用范围与可用费用授权。学生修改某个共享资料，不能借此取得其他教师身份或私人知识写入权。缺失授权只阻断该任务并说明恢复办法，RAG 的正常保存不被连带回滚。

更新依赖多个文件时，以确定的资料版本集合形成一个任务输入。连续保存可在尚未发送阶段合并到最新输入，但不得丢最后一次修改或永久不更新。页面刷新、组件重挂、事件重放、多个引用 Agent 都不能产生重复收费请求。

### 6.2 手动 `↻`

保留每份有生成关系且可编辑 Knowledge 的循环箭头，明确表示“重新生成 Knowledge”，不是浏览器刷新。无需额外 Publish/Confirm；该动作的 accessible name/简短 tooltip 可写“重新生成并覆盖当前 Knowledge”。没有生成配置时不伪造可用按钮。

一次主动点击对应一个稳定意图/幂等键；网络重试和双击只恢复同一操作。之后另一次明确点击可以重新生成，即使 RAG 未变化，也不能被“相同资料已有结果”的永久缓存吞掉。

### 6.3 覆盖人工修改：本次明确变更

**自动 RAG 更新与手动 `↻` 均默认以成功的新生成结果替换当前 Knowledge，包括此前人工修改过的正文。**删除旧逻辑里“teacher-edited head 永不覆盖”这一业务条件，不再弹出保留/覆盖二选一的审批。

“覆盖”是写一个新版本并将其设为 current，不是物理删除旧版。来源、旧文档、旧题目/Rubric 和历史评估仍可追溯。重新生成期间发生的人工修改同样保留成历史版本；该次仍有效的最新生成完成后可以将其替换，不以人工 edit 自动使生成失效。

同时保留并发正确性：绑定更新一代的 RAG 或再次明确发起更新后，旧任务晚到不能反盖新一代结果。判据应是来源/生成意图代次和实际授权，而不是“头版本被手改就永远不许写”。同一生成的重复落库只产生一次新版本。

### 6.4 loading 与失败

真实任务运行时显示小加载符号和 **Generating AI Knowledge**，不增加完成/审核状态徽标。已有完整文档仍可查看；首次没有内容时显示骨架/加载，不伪造空成品。

新的完整文档保存成功后直接刷新内容，无须浏览器手动刷新。重生成失败保留上一份完整可用文档；已经可靠保存的新段落/资产按既有部分成功语义保留可追溯记录，但不能用半份失败正文静默替换整份旧文档。首轮部分成功时可以显示已保存内容与简短失败说明。

Provider 未发送、已接受、接受状态未知分别处理；未知不自动重发或假称未计费。失败应有准确原因和合法恢复动作，不永远 loading，不锁死全站或整个 Chat。

## 7. Memory：轻入口、真数据，不是第三份可编辑文档

Memory 与 RAG/Knowledge 同页显示当前身份有权访问的 Agent/会话入口，不展示学生记忆管理表、向量库、JSON、快照编辑器或新增按钮。

点击 Agent 右侧进入符号后，进入相应 Chats，自动发送一次可见消息：

> 你目前记得我们之前聊过什么？

Agent 必须读取当前身份合法的已保存记录/记忆后作答，不能把 RAG、Agent.md 或模型通用知识冒充与此用户的记忆。没有记忆明确说明没有；不能编造。

同一点击使用 action/request ID，刷新、后退、重新挂载或恢复网络不能重复发消息/创建会话/重复收费。先正确导航与确定身份再发送，失败不误发到另一个 Agent。多个相关会话优先恢复最近有效上下文，必要的会话范围在 Chats 内简洁说明，不先增加一层 Memory 管理页面。

Team 内专属授权成员仍在该 Team 上下文中提及或查询，不绕成无权 Single。若目标课程活动有未结束测评回合，按第 8 节回到原回合，自动消息改为下面这句，并真实显示给用户：

> 请列出本测评回合中我已经提交的作答记录和当前进度，不要提供答案、评分依据或提示。

该查询不算作答、不推进题目、不重新开始测评。老师查询学生情况仍通过自己的 Chats 和 Teacher Tools，只读取允许的 Public 数据；Memory 列表本身不泄漏 Private 内容或数量。

**RAG/Knowledge 更新不删除、重置或改写既有 Memory。**新聊天继续生成新记忆版本，旧回答与对应知识版本保留。必要的摘要再整理只是新增解释，不把以前的错误、提示或重答改成另一段历史。

## 8. Maya Team 测评：一个回合是完整的一次 attempt

### 8.1 三种概念分开

聊天消息是一条 message；一次模型/工具执行是 run；一次从开始到完成或放弃的测评是 assessment attempt（测评回合）。不能把发一条消息叫完成一个测评回合。

本规则适用于配置为本次测评的 Maya Team/诊断配方及其已有活动，不套到所有普通 Agent、写作 Team 或非教学 Maya Team。行为写进自由格式 Agent.md；平台使用通用会话/attempt 状态支持，不通过 Maya/Bowen 等名字猜模式，不另加付费 Planner。

### 8.2 生命周期

```text
开始 → 进行中 ↔ 暂停
           │        │
           ├────────┴→ 完成 → 可以开始新回合
           └─────────→ 明确放弃 → 可以开始新回合
```

暂停保留原 attempt、当前题目、答案和进度，回来继续原回合，不从第一题重来。暂停不是完成或放弃。浏览器刷新、关闭、网络断开、模型失败、停止输出和额度不足都不能自动抹掉 attempt；停止一次输出也不等于丢弃已提交答案。

**只有完成当前回合，或学生明确放弃当前回合，才可开启新回合。**“重做/重新开始”本身不悄悄清空记录：有未结束回合时说明可以继续，或明确表达放弃后重做；学生明确说“放弃本回合并重做”时一次处理，不强迫再点第二次确认。

放弃是保留已有答案并将回合记为未完成，不是删除作答。新回合用新 attempt ID，不复用/覆盖旧答案；未测试的内容不判不会，部分完成不计成完整完成。只有满足本回合配方已经明确的实际结束条件才记为完成，不能把学生说一句“标记完成”当完成证明；提前结束走放弃语义，单说“暂停/停止”默认保留可继续的回合，不擅自放弃。

同一用户、同一课程活动/测评范围最多一个未结束回合；新建 Chat、复制入口、换浏览器或并发点击不能绕开。范围使用服务器的稳定 activity/source 标识，不只绑定聊天 ID、Team 名称或会被改名改变的字段；不把不同课程/活动全部锁在一起。

若原回合 Private、用户从 Public 入口重进，不自动复制原文、改可见性或公开旧记忆；返回原 Private 回合继续，或由其完成/明确放弃后开始独立的新 Public 回合。

### 8.3 回合内允许和不允许

允许：提交当前作答，按规则补交尚未提交的部分，说明不会/明确跳过，查询本人本回合已提交的原始作答及进度，暂停、继续、完成、明确放弃。

不允许：给答案、解题线索、针对当前题的知识讲解、纠错暗示、实时告诉对错/分数/薄弱点、展示参考答案或 Rubric、处理与测评无关的聊天任务。选择下一题可以依据既有回答，但问题本身不得夹带上一题的正确答案或提示。

遇到索要答案或跑题，简短说明并引导回当前题，例如：

> 这轮测评暂不提供答案或提示。你可以继续作答、查看已提交记录、暂停，或者放弃本回合后再讨论。

不是 403 后永久锁死 Chat，也不是按某个关键词拒收消息；原消息可保存，但不冒充答卷、不计题数、不推进回合。若消息同时有合法回答和其他请求，先保留合法回答，拒绝泄题/跑题部分。

“为什么我错了/我会不会这个点”在回合中也不提供实质反馈；“我第 2 题刚才写了什么”返回原作答而不是标准答案。题目只有记录/界面显示问题时可原样重发，不增加解释性线索。

完成或明确放弃后，恢复正常讨论，可解释答案、给反馈或聊其他事情，但不泄漏无权查看的整份题库或其他人数据。后续新回合独立记录；已经看过的解释是实际历史，不能声称从未接触或覆盖成独立首次作答。

### 8.4 状态与模型上下文都要对应

不能只在 Bowen 的 Prompt 写“不提示”，却给被 `@` 的 Maya/Jade/Kaikai 另一条不受约束的答疑通路。Leader、所有成员、Memory 自动查询、知识读取和工具结果呈现都遵守当前 attempt 阶段。

用于内部评估的 Rubric/答案和面向学生的发言上下文分开；不把评估工具原始载荷、内部评价、推理或答案通过 SSE、消息卡片、来源预览、其他对学生的输出路径返回。实现不要求披露模型隐藏推理。

Public Tools / Teacher Tools 两类保持不变，不重建 Internal Workflow 特殊权限层；read/edit/append 和当前调用用途继续由服务验证。用户输入不能伪造 evaluator、attempt、原始回答或正式课程来源；原始回答由服务器先保存。正式 Assessment 修订留历史，不因用户说“改满分”变成真实诊断结果。

这是用户本次明确要求的测评行为，不是偷偷恢复全平台后台限制。不得因此加固定题数、轮数、最大重做次数、字数限制、姓名触发流程或所有聊天必须测评。配方决定覆盖范围与结束条件，平台维护当前 attempt 的合法状态和可恢复动作。

此限制只作用于该测评上下文，不封锁学生其他合法应用或普通 Chat，也不声称能防止外部查资料。真正的权限、安全保护不因学生问“结束”就取消。不能把回合规则扩为账户级禁言、强制完成所有课程或全平台禁止提问。

在通用工具体系内实现通用 attempt 状态与有版本的测评协议；不另造一套只认四个人名的运行器。只修改本次授权的教学配方/模板和对应版本，不批量改写用户无关的 Agent.md。实际保存、加载和子成员调用都需验证这些规则生效，不能只在设计文档里描述。

## 9. 必须写回教学 Agent.md 的规则

不要要求老师另外新建 Team instructions 文件。Leader 的 Agent.md 继续作为协作指令来源；将以下规则合并到本次教学配方的实际 Agent.md 与对应模板中，保留各自原有职责。对老师已自写的正文做可追溯的规则合并，不直接用默认模板覆盖全文。

### 9.1 四位成员共用的测评约定

> 当当前会话处于测评回合中，你只执行与本回合有关的作答收集、记录读取、进度管理、评估协作和后续出题。不要向学生给答案、提示、解题讲解、纠错暗示或实时评分；不要响应无关任务。学生询问已经提交的作答时，返回本人本回合原记录，不追加答案或评价。索要答案或跑题时，简短说明并引导继续、暂停或明确放弃，不锁死对话。暂停保留原回合；只有完成或明确放弃才能开始新回合。完成/放弃后才恢复正常解释和其他交流。不要声称可以把旧作答记录清空来重新开始，不得伪造或改变真实用户、回合、题目、版本或证据来源。

### 9.2 Bowen · Leader

> 一次测评从开始到完成或明确放弃构成一个回合，不是一次消息。开始和续接前读取当前真实 attempt：存在未结束回合就继续，不另开。逐轮接收答案，交给评估成员，依据返回的合法建议出下一题；不提示答案或当场告知对错。不要把查记录、暂停或问答案当成新作答。学生要求重做时，若本回合尚未结束，说明继续或明确放弃后重做；明确放弃后先保留并结束旧回合，再创建新回合。任何阶段都不隐藏已经发生的作答。

### 9.3 Maya

> 根据授权 RAG 生成或更新 Knowledge。测评中可为团队准备题目和必要资料，但对学生不提供当前/后续题目的答案、提示、概念教学或 Rubric；需要解释时引导其先完成或明确放弃本回合。更新 Knowledge 不重置学生正在进行的测评。

### 9.4 Jade

> 根据实际回答和对应冻结题目/Rubric 进行内部评估，提出下一题或追问，不把评估结果或评分标准直接反馈给学生。追问用于取得新证据，不能夹带解题线索或暗示上题哪里错误。不要因漏答或未测试就判不会；学生直接 @ 你时同样遵守回合约定。

### 9.5 Kaikai

> 保存并整理真实回答与评估的知识边界。回合内面对学生，只提供本人本回合已提交答案和进度，不输出对错、掌握评价、标准答案或提示。完成或明确放弃后，再在权限范围内提供个人总结和解释。老师的 Public 课程汇总始终依据有效来源与真实 attempt 状态，不能把中途放弃算完整完成，不把 Private 或普通自定义练习冒充正式诊断。

既有提示后作答的历史数据不删除、不重新标注；新测评配方不再设计“先提示后答对”的教学路径。四个人名只是配方显示名，更名后规则仍应成立。

## 10. 知识更新、测评版本和 Memory 的衔接

RAG/Knowledge 变化只影响后续授权读取，不改写已经发给学生的题目、Rubric、作答与 Assessment。每道题呈现时冻结题目和 Rubric 的实际版本，评估按同一版本；后台重生成不能让学生答到一半更换标准答案。

新题依据当前活动既有版本策略读取可用 Knowledge，并记录真实版本；不为此次 UI 重构另造隐形全局冻结，也不偷偷把历史报告切到新定义。跨版本统计注明来源，无法对应时不编造映射。

RAG 修改不自动结束/放弃学生回合，不清空个人记忆。真正撤销资料授权时，按权限暂停相关操作并提供继续恢复或明确放弃路径，不能继续读取无权资料。

报告分别统计独立参与人数、回合数、完成数、放弃数、进行中/暂停数与有效作答数。重做不能重复计为新学生；Private 不出现；作答记录查询不产生新 Assessment。正式课程数据与自定义练习通过服务器来源关系区分。

## 11. Tools、数据权限、Provider 与失败处理

### 11.1 只有维护层注册，分 Public／Student／Teacher 三类

保留你已经吸收的新工具设计，不退回旧稿：

- Student 可获得 **Public Tools + Student Tools**。
- Teacher 可获得 **Public Tools + Teacher Tools**；工具分类不授予跨用户数据权限。
- 只有维护层注册、修改和移除 Tool。老师与学生都不上传 Python／Tool，不安装任意 MCP，不需要新增工具绑定面板。
- 不另设 Internal Workflow Tools 或 Maya-Team-only 特殊分类。学生自建 Agent/Team 也能使用其已授权的学习与评估能力；正式记录的 edit 权须单独核验目标资源和任务授权。
- 工具集合由当前实际使用者的课程角色和已注册能力确定，不能从 Agent／Team 创建者继承教师身份，也不用额外 Planner 判断 Agent.md “配不配用某 Tool”。Agent.md 指导选择和使用工具，不授予权限。

本次恢复报告称统一工具注册实现尚未完成。核对真实代码后复用已有等价实现，没有才建立适合仓库结构的最小 registry；不把某个特定目录名是否存在当实现或未实现的唯一证据。

### 11.2 Read／Edit 等是资源权限，不是另加一套业务门槛

Public Tools 提供通用资源操作，Student Tools 提供本人学习、测评和记忆能力；具体分类以维护层注册合同为准。函数名可贴合现有合同；每项操作都检查当前身份对具体对象的 read／edit／append 权限，具备 read 不自动具备 edit。

Teacher Tools 增加允许范围内的课程 Public 学习证据读取、聚合、课程报告和课程发布。即便某个 read_assessment 工具对两种身份都可用，教师的跨学生读取仍须符合教师课程权限与来源的 Public 条件。不能因为工具为 Public 就开放所有记录。

`read_other_student_private_chat` 及等价越权工具不注册。Teacher 不得读取学生 Private Chat／Assessment／Memory，也不能以“审计”“恢复”“管理员提示”绕过产品界限。

Assessment 的 edit 是创建修订版，保留真实操作者、生成过程和来源；不允许模型伪造 actor/evaluator、正式来源或原始分数。原始答案与 Evidence 只追加，重答产生新记录。自定义练习、用户修订与正式测评的来源由服务器赋值，不能仅凭处在课程 Chat 中就把用户手工改分标为独立模型评估。

`edit_session_state` 只允许合法业务字段和状态转换，不能编辑身份、课程角色、Private/Public、账本、确认、来源或任务权限。限制这些字段是数据/权限契约，不是隐形教学流程。

### 11.3 Chat 删除必须有完整业务结果

补齐恢复报告指出的 Foreign Key 接缝。删除 Chat 不能直接触发数据库异常，也不能为了删干净而级联抹除原始证据。

复用现有 tombstone／撤回机制：用户删除后，会话从其正常列表移除，未完成任务与迟到写入被隔离，相关数据退出教师查询和报告；旧产物和下载按来源依赖失效。因审计和历史关系保留的数据只能按既有存储/清理规则处理，不能继续以可见学习记录使用。不要把技术保留宣传成“所有副本立即物理删除”。

允许用户解除失效绑定、继续其他合法对话；可恢复失败要提供恢复动作，不能只暴露 FK error。与活动 attempt 的关系要保持真实：删除/撤回不冒充“完成”，更不能留下指向不可恢复会话的永久活动锁。先遵守现有明确删除语义，在必要处使用可追溯的结束/撤回记录，不悄悄删除回答来开启新回合。

### 11.4 Provider 和运行恢复必须真正接通

继续精确锁定 Agno **3.0.11** 与公开 SDK 薄适配，不重复 W0、不复制上游源码。公开接口确实不足时，先给可复现证据，再提出最小适配/移植选择。

收尾真实 Team 调用链：Agno 最终消息 → 实际请求字节与授权 → 每次实际调用账本 → transport → 持久接受阶段 → 成员结果/工具副作用 → SSE 文字与恢复。不能把“一名成员”误当成“一次模型请求”。缺 usage 不丢有效正文；unknown 不盲重发；明确未发送则释放内部预留/请求计数，不声称已对供应商完成退款。

真正的暂停/继续还需要持久恢复端点或等价命令：新实例读取状态、核对授权、恢复已完成回执和待执行动作；SSE 重连只重放/观察，不等于继续一个暂停的执行。继续不得重做成功副作用，也不得把旧回包写到新会话。

**教师资料预授权＋学生精确外发确认是待收敛的工程设计，不是用户已接受的额外点击流程。**核对既有 Provider 披露规则和实际授权：教师不能为了确认模型调用而查看学生 Private 内容；学生不能获得教师内部原件。可在后台分别关联资料使用授权与个人会话授权，但不得默认增加“老师每条批准学生请求”或“每条消息弹确认”的产品仪式。

已有授权在其真实有效范围内复用；新用途/主体/资料/政策发生必要变化时重新核对，不能拿旧确认伪称覆盖新外发。确实缺少授权就准确暂停该次外发并指向最少的有效恢复入口，不伪造确认，不永久锁会话。此设计不能变成生成内容的 Ready／Review／Approve 闸门。

### 11.5 不新增隐藏的正常使用限制

不加入固定轮数、字数、总 RAG 长度、隐形次数/费用配额、关键词拒绝、静默历史/资料截断、额外职责 Planner 或内容质量审核。新测评协议是本文件明确要求的局部行为，不是这些全平台限制的复活。

普通权限/资料/工具失败返回结构化结果，让 Agent 解释并继续合法操作；只停止对应动作。凭据失效、真实上下文容量、无可用题目、网络失败和接受状态未知分别给真实原因与恢复办法。预算或服务容量是真实环境约束，不将其伪装为模型理解问题；没有被授权的新费用不自动发生。

保留审计、幂等、并发、资料授权、版本和来源真实性验证。只删除与本次明确产品变更冲突的旧规则，不因“不要后台限制”绕过数据正确性或安全要求。

## Latest Chats UI boundary — 2026-10-05

This user supplement supersedes earlier visible attempt controls in this document.
Chats keeps the existing General Chat layout, history, composer and message/error
presentation for Agent, Team and Maya Team. Attempt states remain backend business
state; do not expose an Assessment dashboard, state card, progress panel, dedicated
input or Pause/Continue/Abandon/Restart button group.

Students start, answer, pause, continue, abandon, explicitly abandon-and-redo and
query submitted records through natural language in ordinary Chat. A paused attempt
must allow the composer to submit a message. Only a valid resume action restores
that same attempt; querying records or abandoning must not first resume grading.
Maya Team is a configured Team using the same Chat interface. Tool/permission/state
failures reuse existing messages/errors with a short explanation and next step.
Brainform remains the separate information-management interface. Backend permissions,
privacy, receipts, idempotency and explicit acceptance recovery stay enforced.
