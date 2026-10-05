# 正式诊断 Agent.md 示例

这四份可编辑文件对应一个示例 Maya Team：Bowen 主持，Jade 评估，Kaikai 总结与查询报告，Maya 提供课程知识。显示名字可以更换；服务器依据已发布版本、真实成员、当前学生与任务建立授权。

需要首轮派生 Knowledge 的 Agent 使用既有 **Create AI Knowledge** 入口，导入对应 Agent.md 与 Markdown 课件，再用工作台 Done 发起生成；普通 New Agent 保持原行为，单独上传 RAG 不会自动创建派生文档。在 Brainform 查看生成的 Knowledge，把正式诊断需要的 Knowledge 放入 Team 共享资料，选择主持 Agent 为 Leader，将课程 Team 设为 Public 并保存。学生从 Chats → New → Maya Team 选择该 Team，再选择自己的 Private 或 Public 会话。

Agent.md 中三条 `MAYA-ASSESSMENT-*` 配方声明定义正式诊断的选题和完成规则；另外两份文件的 role 声明标记候选执行职责。它们不授予全局权限、不继承教师身份，也不允许模型自填授权。原始回答、题目版本、回合状态和发布关系仍由服务器校验。

普通 Agent／Team 的自由用途不需要这些声明。教师无需逐个绑定 Toolkit，也不需要批准 AI 生成内容。课程外发授权使用现有 Provider 披露入口，与内容审核分开。

示例不包含学生数据、账户或凭据。真实测试时应通过正常发布与会话入口建立关系；不得直接插入已完成评估或假授权来冒充产品验证。实现与验收状态以 [PROJECT](../../PROJECT.md) 为准。
