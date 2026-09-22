# 默认 Markdown 教学规则与生成输入

教学内容只维护 [Prompt CN](../../backend/app/modules/debates/default_rules/zh.md) 和
[Prompt EN](../../backend/app/modules/debates/default_rules/en.md)，此文不重复复制八份
完整 Prompt。教师创建页的 Ruleset 编辑器以侧栏 Done 保存表单，创建 Debate 时冻结
两份 Markdown 与四轮 System 消息。已有课堂继续读取自己的快照，不随默认文件修改。

## 实际发送

每次 Debate 生成发送一条 System 和一条 User JSON。System 是冻结教学 Markdown
加语言、当前轮次、输出字段、来源与问题/弹幕路由协议；不解析标题决定教学流程。
User 包含当前 Agent 的原文、Topic/Background、历史、来源及本轮资料。

新输入保留兼容字段名 `persona`，值为 `{ "name": "Agent name", "markdown": "原文" }`；
不编译、扩写或验证人设章节。历史五段 Persona 仍可读取，不回写已保存内容。
`persona_spec_hash` 在新输入中绑定原文 SHA-256，不表示存在另一份 Persona。

Agent.md 为中英文自由 Markdown，最大 12,000 字符；默认模板只是写作起点。
RAG 文件同样自由，每个最大 100,000 字符，不要求标题、关键词或特定观点；
`.md`/UTF-8 读取、文件路径和账号访问边界不等于正文规则。展示不会执行上传的脚本。
检索取自己的不可变知识快照，来源绑定不认证事实正确性。

前三轮 Preview，第四轮现场生成。后续发言读取此前成功的完整发言，包括同轮前序；
第三轮讨论记忆独立保存，第四轮和 Report 使用它，不写回 Agent.md。
模型输出正文不按长短、风格或观点自动拒收，损坏的结构最多按原授权修复一次。
恢复使用冻结输入与哈希，不重新生成已接受结果。

## Chats

单聊只使用已发布 Agent.md 和对应 RAG；消息按会话保存，重新进入仍发送同一会话的
成功历史，New 才另开会话。没有跨会话用户画像，也没有独立 Test Chat 或草稿聊天。
请求预算、同一请求去重、来源与所有权边界由原有服务负责。

## 证据边界

[four-round-example.json](four-round-example.json) 是保留的旧结构合成样例，不是当前
自由 Markdown 的模板或真实课堂记录。实际产品输入见
[generation_adapter.py](../../backend/app/modules/debates/playback/generation_adapter.py)、
[segments.py](../../backend/app/modules/debates/generation/segments.py) 与
[chat_provider.py](../../backend/app/modules/workspace/chat_provider.py)。
Prompt 是模型指导，不保证回答质量；真实 RAG 教学质量仍需人工检查。
