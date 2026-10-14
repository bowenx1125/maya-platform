# 正式诊断 Agent.md 示例

这四份可编辑文件是课后诊断 Team 的四个角色，建立在普通 Agent 上。苏格拉底、柏拉图、老子没有这些声明，不能拿来做正式测评。显示名字可以更换；服务器依据已发布版本、真实成员、当前学生与任务建立授权。

1. `maya.agent.md` 根据课件整理知识点和题目。教师在自己的已发布 Agent 单聊里调用 `generate_agent_knowledge`，或在发布时提交明确的生成意图。工具只读取该 Agent 已选的 RAG，由一次性生成写成 Concepts、带参考答案和 Rubric 的 Questions、Notes。聊天里的临场想法不会另写进 Knowledge。
2. `bowen.agent.md` 是 Guide。三条 `MAYA-ASSESSMENT-*` 声明只放在这一份，用来选题和判断完成。`# Team Ruleset` → `## Formal assessment` 用花名册显示名写 `answer_recorder`、`question_guide`、`scorer`、`summarizer`、`student_round_order`。缺任何一项，正式测评拒绝且不创建 attempt。
3. `jade.agent.md` 是 scorer。学生每答一题，先由服务器要求的写工具记下，再由 Guide 出下一题。Jade 随后用 `edit_assessment` 按 Rubric 评估，并从服务器给出的未问题目里选择追问。
4. `kaikai.agent.md` 是 summarizer。全部答完后说「正在总结答案」，并用 `update_learning_boundary` 把结果分成有掌握证据、作答显示的薄弱点、尚未验证。漏答和没问到的归入尚未验证。教师查统计和下报告时用 `list_course_assessments`、`read_course_statistics`、`create_course_report`，只覆盖学生设为 Public 的正式记录。报告链接只由服务器附加。

Agent 在 **Studyform** 用共用工作台创建，资料从 **Brainform** 选择 RAG 或已有 Knowledge。需要首轮派生 Knowledge 时，Done 提交明确生成意图，或在教师自己的 Agent Chat 让 Agent 调用 `generate_agent_knowledge`；同源已生成/生成中任务复用同一 canonical Set。单独上传无依赖 RAG 不会自动创建派生文档。在 Brainform 查看生成的 Knowledge，把正式诊断需要的 Knowledge 放入 Team 共享资料，选择主持 Agent 为 Leader，将课程 Team 设为 Public 并保存。学生在 Chatform 点 New，从 Chat with 选择该 Team，用 Public/Private 切换决定会话是否向教师开放。

学生不开始测试时是练习，不写入答题记录；明确开始后才是正式测试。第一轮按题库抽查，Jade 评估后可以从服务器给出的候选题里选追问；"结束答题"按提前交卷保存，只有"放弃"不保留本次记录。Kaikai 把结果分为掌握证据、薄弱点和尚未验证，教师报告按学生列出。

Agent.md 中三条 `MAYA-ASSESSMENT-*` 配方声明定义正式诊断的选题和完成规则。发言顺序来自 Guide 的 `## Formal assessment`，不来自 `MAYA-ASSESSMENT-ROLE`。`assessment_active` 只是账本标记。它们不授予全局权限、不继承教师身份，也不允许模型自填授权。原始回答、题目版本、回合状态和发布关系仍由服务器校验。优先级是授权、测评账本、Team Ruleset。

普通 Agent／Team 的自由用途不需要这些声明。教师无需逐个绑定 Toolkit，也不需要批准 AI 生成内容。教师明确保存/生成无需额外 Knowledge Provider 确认；实际 actor/source 权限与政策仍核查。Team 的准确资源外发授权沿已有入口单独检查，与内容审核分开。

示例不包含学生数据、账户或凭据。真实测试时应通过正常发布与会话入口建立关系；不得直接插入已完成评估或假授权来冒充产品验证。实现与验收状态以 [PROJECT](../../PROJECT.md) 为准。
