# 2026-11-10 RAG 面板方案

给产品负责人确认。确认前不改产品代码，不合并，不部署，不开
`DEMO_MODE` / `DEMO_QUICK_LOGIN`。

对照图是仿真页 `mockup.html`，按 Agent 编辑页现在的 arcade sticker 尺寸和颜色画的
（3px 黑边、硬阴影、青柠 / 品红 / 黄）。没有启动产品，所以不是线上组件的截图。
页面里的文件名、声音名都是假的，并标了 **EXAMPLE DATA**。状态对照图上的
`−2px`、`+6px` 是说明标签，不是产品文案。

## 请确认的三件事

1. Agent 编辑页这块面板的标题从 Brainform 改成 **RAG**。侧栏分组名仍叫
   Brainform，导览步骤也不改。
2. 去掉面板里的 **RAG**、**Knowledge** 两个小标题，以及整个 Knowledge 区块。
   面板里只留 RAG 卡片和右上角 New。
3. RAG 卡片和 Voice 唱片都加上选择动效。推荐 **变体 A · Press key**。

## 现在这块面板

标题来自 `t("brainform")`，写在
`frontend/components/agent-workspace.tsx` 的 `SectionCard` 上。两个小标题是同文件里的
`<h3>{t("rag")}</h3>` 和 `<h3>{t("brainformKnowledgeHeading")}</h3>`。RAG 卡片样式是
同文件末尾的 `RAG_STICKER` / `RagStickerFace`。Voice 是旁边那块粉红面板，唱片在
`frontend/components/voice/voice-library.tsx` 的 `VoiceDisc`。

点 RAG 卡片今天并不是完全没样式：选中后会变成青柠底、右上角粉勾、上移 3px 并转
−1°。缺的是「还没点的时候也看得出能点」：

- 没有 hover，没有按下。阴影是 `0 4px 0`，边是 2.5px。旁边的 New、眼睛、下载已经在用
  `PRESS_MOTION`：悬停上移 2px，按下下沉 6px、阴影收到 0，过渡 150ms，按下 80ms。
- 选中主要靠青柠。粉勾在，但没有文字，边也没有加粗。
- 焦点环挂在视觉上隐藏的 checkbox 上，粉色 `outline`，偏移 2px。粉面板上会和底色贴在一起。
- 眼睛和下载是 40px（`size-10`），小于 44px。
- Voice 选中是青柠圆心、青柠环，再加上不停旋转。`prefers-reduced-motion` 会停掉旋转，
  停掉之后只剩颜色。

## 三个变体

五种状态都在对照图里：Default、Hover、Pressed、Selected、Focus。黑线是静止时卡片顶边的位置。
RAG 卡片画在青底上，Voice 唱片画在粉底上，和编辑页一致。

| 变体                      | 悬停 / 按下                                                                              | 选中（不只靠颜色）                                                                         | 焦点                                                        | 优点                                                                                             | 缺点                                                                                               |
| ------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| **A · Press key（推荐）** | 上移 2px，阴影 6px 收到 8px；按下下沉 6px，阴影收到 0。150ms，按下 80ms。和 New 同一套。 | 粉勾 + 黑底白字 **Selected** + 边从 3px 加到 4px。Voice 的名字牌同样加粗，并停掉无限旋转。 | 3px 黑环，外面再一圈 3px 黄。青底、粉底、青柠底上都看得清。 | 和现有按钮是同一种手感，实现就是把 `PRESS_MOTION` 用到卡片上。减弱动效之后勾、文字、加粗边还在。 | 2px 的悬停在静止截图里很轻。按下时阴影消失，这个比较明显。                                         |
| **B · Stamp tilt**        | 向左上移 2px 并转 −1.5°，阴影改成斜向 6px。按下向右下 3px，阴影收到 0。                  | 粉勾 + 黄色 **ON** 胶带 + 4px 边，卡片再转 −2°。                                           | 3px 黑色虚线环。虚线本身不是颜色。                          | 更像一张被盖过章的贴纸，和现在选中时的那一点旋转接近。                                           | 网格里一转就容易挤到隔壁卡片。焦点环会跟着转，看起来歪。减弱动效必须取消旋转，胶带和勾要单独留着。 |
| **C · Plate**             | 不抬起。左边长出 16px 黄条。按下只下沉 4px，卡片底色变成纸黄。                           | 粉勾 + 4px 边 + 整条黄色 **SELECTED** 字牌。                                               | 3px 黑环，外面一圈品红。                                    | 选中最容易读，字牌不依赖位移。对怕动的人更稳。                                                   | 和按钮的按压语言不一致。黄条占卡片左侧。字牌把卡片垫高，两列对齐会变脏。                           |

推荐 A。编辑页的 New、眼睛、下载已经在教用户「能点的东西会抬起、按下会沉下去」。
卡片沿用这一套，比再发明一种倾斜或字牌便宜，也更不容易在两列网格里互相碰撞。
选中仍然用勾、Selected 和加粗边，满足「不能只靠颜色」。

减弱动效时：取消 translate / rotate，保留颜色、阴影、勾、文字和加粗边。过渡仍约 150ms，
只过渡颜色和阴影。mockup 用系统的 `prefers-reduced-motion`，也可以给 `<html class="reduce">`
看同一套规则。

## 实现时的规格（确认后才写进产品）

- 可点区域至少 44px。RAG 整张卡片（眼睛和下载除外）都是选择热区。这两个图标按钮改成 44×44。
  Voice 唱片现在是 64px，热区包含唱片和名字牌。
- 语义用控件自带的 role，不用 `aria-selected`。RAG 可以多选，继续用
  `input type="checkbox"`（role 就是 checkbox，选中是 checked）。Voice 只能选一个，
  继续用 `radiogroup` + `radio`。`aria-pressed` 适合「几个都可以按下」的切换按钮，
  表达不了 Voice 的单选，所以不作为这套控件的首选。
- 焦点用 `:focus-visible`，3px 黑环、偏移 3px，再加一圈黄。不要用只有品红的环，粉底上会消失。
- 图标按钮的点击不能冒泡成「选中这张卡片」。它们现在就在 label 外面，保持这样。
- 面板标题只改这一处 `SectionCard` 的文案。不要改 `app-shell.tsx` 里侧栏分组
  `"Brainform"`，也不要改导览 `tourBrainformTitle`。
- 帮助文案 `agent.brainform` 现在写的是 “Choose RAG source files and existing Knowledge…”。
  面板不再放 Knowledge 之后，这句要改成只讲 RAG。UI 仍只写英文。
- 没有 RAG 时，沿用现在的空状态文案，不要留下 “No Knowledge yet.”。

## 拿掉面板里的 Knowledge 时不能做的事

面板上的 Knowledge 是 **Knowledge Set**（一套可绑定的 canonical Markdown）。
RAG 文件在接口里也叫 knowledge document。下面这些名字像 Knowledge，其实是 RAG，
不能跟着面板区块一起删：

- `PlatformApi.knowledge`、`uploadKnowledge`、`uploadWorkspaceKnowledge`、
  `downloadKnowledge`、`hideKnowledge`、`knowledgeAffectedAgents`
- `frontend/lib/group-library.ts`（小组 RAG 文件列表，404 时退回空列表）
- `frontend/components/knowledge-check.tsx`（RAG 卡片上的查看 / 下载）
- `frontend/components/knowledge/markdown-editor.tsx`（RAG 新建和编辑也在用）
- `frontend/components/knowledge/rag-album.tsx`

Knowledge Set 的绑定存在 Agent 上。面板上的勾选今天会调用
`replaceAgentKnowledgeSets`。藏起区块之后，保存或 Done **不能**把 `set_ids` 写成 `[]`，
否则会把已经绑上的 Set 清掉。做法：继续从 `agentKnowledge.sets` 读入现有 id，
界面不再提供修改，只有 id 真的变了才提交。并加一条测试：打开编辑页再按 Done，
不会调用 `replaceAgentKnowledgeSets`。

`frontend/tests/agent-ai-knowledge-flow.test.tsx` 里
“selects a Knowledge set from the Agent editor” 会失败，因为那条测试就是在这个面板里
点 Knowledge 勾选。应改成「面板上没有这个勾选，Done 也不提交空的 set id」。
生成流程 `?flow=ai-knowledge` 仍会在发布后跳到 `/teacher/knowledge`，那条路径不要在这次面板改动里拆掉。

## Knowledge 依赖清单

范围只看前端。分两种后果：「只拿掉这块面板的 Knowledge 区块」和「把整个 Knowledge Set
功能从前端删掉」。这次方案只建议第一种。第二种会坏，列在这里是为了确认时不要一起删。

### 只动这块面板

| 路径                                                                                                   | 用途                                                                                                                         | 拿掉面板区块之后                                                                                                                      |
| ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/components/agent-workspace.tsx`                                                              | 面板标题、两个小标题、Knowledge 勾选列表、`knowledgeSets` / `replaceAgentKnowledgeSets`、生成完成后跳到 `/teacher/knowledge` | 要改标题和两处小标题，去掉 Knowledge 列表的渲染。保留已绑定 id，不要提交空列表。生成跳转先留着。                                      |
| `frontend/lib/i18n.ts` 的 `brainform`                                                                  | 这块面板的标题，现在是 “Brainform”                                                                                           | 若只改这一处标题，会连别的引用一起变。现在全前端只有这一处 `t("brainform")`。可以改成 “RAG”，或给面板单独加一个键，避免以后侧栏误用。 |
| `frontend/lib/i18n.ts` 的 `brainformKnowledgeHeading`、`brainformKnowledgeEmpty`、`agentKnowledgeSets` | 面板小标题 “Knowledge”、空状态 “No Knowledge yet.”、Agent 的 Set 列表标题                                                    | 面板不再渲染。字符串可以留着，Brainform 专辑页还在用前两个。                                                                          |
| `frontend/lib/ui-guide-copy.ts` 的 `agent.brainform`、`agent.knowledgeSets`                            | 面板标题上的帮助，以及 Set 绑定的帮助                                                                                        | `agent.brainform` 要改成只描述 RAG。`agent.knowledgeSets` 随勾选一起从面板消失，Team 页的帮助是另一条。                               |
| `frontend/tests/agent-ai-knowledge-flow.test.tsx`                                                      | 断言编辑页能勾选 Knowledge Set，以及生成流程会跳到 `/teacher/knowledge`                                                      | 勾选那条要改。跳转那几条在生成流程还在时仍应通过。                                                                                    |

下面这些测试只是给 Agent 编辑页准备了 `knowledgeSets` / `replaceAgentKnowledgeSets`
的空实现，让页面能渲染。区块去掉后，只要组件不再无条件调用它们，这些桩可以留着，
测试本身不用为了「标题还在」而改：

- `frontend/tests/teacher-open-student-agent.test.tsx`
- `frontend/tests/workspace-agent-flow.test.tsx`
- `frontend/tests/agent-issue-bar.test.tsx`
- `frontend/tests/avatar-draft-persistence.test.tsx`
- `frontend/tests/w1-personal-workspace.test.tsx`
- `frontend/tests/wave1-ui-idempotency.test.tsx`
- `frontend/tests/wave1c-workbench-locale.integration.test.tsx`

### 整段删掉才会坏，这次不要动

这些仍是活的入口。只藏起 Agent 面板里的区块，它们继续工作。

路由和重定向：

| 路径                                                                     | 用途                                                                     | 删掉整个功能会怎样                                           |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------ | ------------------------------------------------------------ |
| `frontend/app/teacher/knowledge/page.tsx`                                | 教师 Knowledge 专辑。没有 `group_id` 时只渲染 Knowledge。                | 教师侧栏和旧书签 404。生成完成跳转没有落点。                 |
| `frontend/app/student/knowledge/page.tsx`                                | 学生仍挂 `BrainformWorkspace`。学生界面不画 Knowledge 区块，但路由还在。 | 旧链接断。学生 RAG 的正式入口是 `/student/rag`，不是这一页。 |
| `frontend/app/teacher/groups/[group_id]/knowledge/page.tsx`              | 旧地址重定向到 `/teacher/knowledge`。                                    | 旧书签断。                                                   |
| `frontend/app/student/groups/[group_id]/knowledge/page.tsx`              | 旧地址重定向到 `/student/knowledge`。                                    | 同上。                                                       |
| `frontend/app/teacher/studyform/page.tsx`                                | `knowledge-view` / `knowledge-edit` 重定向到 `/teacher/knowledge`。      | 从旧 Studyform 链接进来的编辑打不开。                        |
| `frontend/app/student/groups/[group_id]/page.tsx`                        | 学生侧同样的 mode 重定向。                                               | 同上。                                                       |
| `frontend/app/teacher/agents/[agent_id]/page.tsx`                        | `flow=ai-knowledge` 时把工作台放进生成流程。                             | 从 Agent 发布并生成 Knowledge 的入口没了。                   |
| `frontend/app/teacher/rag/page.tsx`、`frontend/app/student/rag/page.tsx` | RAG 自己的页，不是 Knowledge Set。                                       | 不要当 Knowledge 删。它们用的是 RAG 专辑。                   |

导航、专辑、Team：

| 路径                                                    | 用途                                                                                                                   | 删掉整个功能会怎样                                                                        |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `frontend/components/app-shell.tsx`                     | 教师侧栏 Brainform 下的 Knowledge 链接，指向 `/teacher/knowledge`。学生侧栏没有这一项。高亮表也认这两条路径。          | 侧栏少一项，高亮和导览目标要一起改。学生本来就没有这个链接。                              |
| `frontend/components/knowledge/brainform-workspace.tsx` | Knowledge 专辑：列表、新建、编辑、下载、删除、生成轮询。也负责 RAG 页。                                                | 不能整文件删。只能摘 Knowledge 分支，RAG 页还在这一个组件里。                             |
| `frontend/components/knowledge/knowledge-album.tsx`     | Knowledge 卡片、图示、专辑顶栏。                                                                                       | 专辑页失去卡片。RAG 专辑不依赖它。                                                        |
| `frontend/components/knowledge/knowledge-mutation.ts`   | Knowledge 写入的幂等包装。Brainform 工作区在用。                                                                       | 专辑上的保存 / 删除失去统一的重试身份。                                                   |
| `frontend/components/teacher-workspace.tsx`             | 把 `knowledgeHref` 传进工作台，生成任务打开对应的 Set。                                                                | 从教师 Agent 进入生成结果的链接断。                                                       |
| `frontend/components/chats/team-entry-flow.tsx`         | Team 新建 / 编辑里的 Shared Knowledge。读取 `brainformKnowledge` 或 `knowledgeSets`，提交 `shared_knowledge_set_ids`。 | Team 不能再选共享 Set。空列表文案是 “No Knowledge yet.”。这是另一块 UI，不是 Agent 面板。 |

接口（都在 `frontend/lib/api/platform.ts`，类型在 `frontend/lib/api/generated/schema.d.ts`）：

| 方法                                                                             | 用途                              | 删掉整个功能会怎样                       |
| -------------------------------------------------------------------------------- | --------------------------------- | ---------------------------------------- |
| `knowledgeSets`                                                                  | 课程下的 Knowledge Set 列表。     | 面板和 Team 选择器没有数据。             |
| `agentKnowledgeSets` / `replaceAgentKnowledgeSets`                               | 读、写 Agent 绑定了哪些 Set。     | 绑定位只剩服务器上的旧值，前端不能再改。 |
| `createKnowledgeSet`、`knowledgeSet`、`updateKnowledgeSet`、`deleteKnowledgeSet` | Set 的创建、读取、改名、删除。    | 专辑页的写操作没了。                     |
| `knowledgeMarkdown`、`saveKnowledgeMarkdown`                                     | 读、写 Set 的 Markdown。          | 专辑编辑器打不开、存不上。               |
| `knowledgeGenerationJob`                                                         | 生成任务状态。                    | 专辑上的进度轮询停。                     |
| `brainformKnowledge`                                                             | 给 Brainform / Team 用的 Set 行。 | Team 共享列表和专辑的行数据没了。        |

文案和帮助（都在 `frontend/lib/i18n.ts`，帮助在 `frontend/lib/ui-guide-copy.ts`）：

- 专辑和编辑：`brainformKnowledgeHeading`、`brainformKnowledgeIntro`、`brainformKnowledgeEmpty`、`brainformNewKnowledge`、`brainformEditKnowledgeNamed`、`brainformViewKnowledgeNamed`、`brainformDeleteKnowledgeNamed`、`brainformDeleteKnowledgeConfirm`、`brainformKnowledgeDeleted`、`brainformKnowledgeSaved`、`brainformKnowledgeConflictDraftKept`、`brainformNoKnowledgeDocument`、`brainformKnowledgeFirstVersionEmpty`、`brainformRegenerate`、`brainformGenerating`、`knowledgeGeneration*`。
- Team：`teamSharedKnowledge`、`teamSharedKnowledgeHelp`、`teamNoSharedKnowledge`，以及帮助键 `chat.teamSharedKnowledge`。
- 生成流程：`aiKnowledgeFlowIntro`、`aiKnowledgeSourcesRequired`、`generationReceiptMissing`、`errorKnowledgeSourcesMissing`。
- 学生首页 `studentGuideKnowledge` 的英文是 “Add the RAG”，链接到 `/student/rag?...&mode=rag-new`。键名像 Knowledge，行为是 RAG。不要删这个引导步骤。

会跟着专辑或 Team 一起失败的测试（这次面板改动不要改它们）：

- `frontend/tests/brainform-workspace.test.tsx`（页面上要有名为 Knowledge 的 region）
- `frontend/tests/brainform-edit-view-download.test.tsx`
- `frontend/tests/brainform-polling.test.tsx`
- `frontend/tests/brainform-legacy-role.test.tsx`（学生 `/student/knowledge`）
- `frontend/tests/brainform-memory-assessment.test.tsx`
- `frontend/tests/knowledge-editor.test.tsx`
- `frontend/tests/page-load-cache.test.tsx`
- `frontend/tests/page-load-round-trips.test.tsx`
- `frontend/tests/platform-brainform-api.test.ts`
- `frontend/tests/platform-read-timeout.test.ts`（含 `brainformKnowledge` 超时）
- `frontend/tests/sidebar.test.tsx`、`frontend/tests/sidebar-lit.test.ts`（教师侧栏 Knowledge → `/teacher/knowledge`）
- `frontend/tests/shell-group-scope.test.tsx`（访问小组时不出现 Knowledge 链接）
- `frontend/tests/pw3-e-shell.test.tsx`、`frontend/tests/pw3-e-teacher.test.tsx`
- `frontend/tests/team-chat.test.tsx`、`frontend/tests/platform-team-api.test.ts`（Team 的 `shared_knowledge_set_ids`）

和 RAG 检索有关、名字里带 knowledge，但不是这块面板的 Set 列表：
`frontend/components/chats/check-rag.tsx`、`frontend/tests/check-rag.test.tsx`、
`frontend/tests/segment-rag.test.tsx`、`frontend/tests/debate-stage-segment-rag.test.tsx`、
`frontend/components/debate/stage/labels.ts`。辩论「没有匹配到的 knowledge sources」
是检索结果文案，不是面板上的 Knowledge 区块。

## 怎么看 mockup

用浏览器打开 `docs/ui-proposals/2026-11-10-rag-panel/mockup.html`。字体在同目录
`fonts/`。布局页可以点卡片、点唱片，也可以 Tab 看焦点环。状态图是冻住的，避免鼠标再改状态。

查询参数：`?shot=layout`、`?shot=a`、`?shot=b`、`?shot=c`、`?shot=a-reduce`。

截图（在评审附件里，不放进仓库）：

- `rag_panel_proposed_1440.png`：推荐方案，视口宽 1440。
- `rag_panel_proposed_390.png`：同一页，视口宽 390。卡片改成一列，Voice 唱片换行。
- `rag_voice_states_a_press_key.png`
- `rag_voice_states_b_stamp_tilt.png`
- `rag_voice_states_c_plate.png`
- `rag_voice_states_a_reduced_motion.png`：变体 A 在减弱动效下，位移关掉，勾和文字还在。
