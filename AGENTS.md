# Maya Platform Agent Rules

1. 开始任何任务前，完整阅读根目录 `Project.md`，再阅读任务相关 Gate、代码和测试。
2. 当前产品范围以 `Project.md` 为准；`AI文化互鉴教学平台-需求文档.md` 只保存原始需求。
3. 不从参考仓库复制任何实现代码或领域模型；只能参考交互、算法、分层与测试思路。
4. 工作必须限定文件所有权；不得回滚、覆盖或无差别格式化其他并行任务的修改。
5. 前端保持 Provider-neutral：不得出现供应商 Key、外部音色 ID、私有路径或必须由浏览器理解的供应商协议。
6. 本私有团队仓库只允许两类凭据文件进入 Git：
   - `backend/config/demo-accounts/accounts.private.md`
   - `backend/config/demo_users.yaml`
7. `.env`、数据库、WAL/SHM、运行 Agent/Debate、快照、生成音频、个人音频、`private-inputs/`、日志与缓存不得提交。
8. CI 与常规测试只使用 Mock Provider；任何真实调用必须单独获得用户授权。
9. Luna 负责实现与自测；Sol 负责合同、风险与 Gate 审计。Worker 不得审批自己的 Gate。
10. 报告必须列出真实执行的命令、结果、失败项和 Commit SHA；不得用历史结果冒充当前 HEAD。
11. P0/P1 未关闭时返回 `CHANGES_REQUIRED`，不得声称对应 Wave 或完整 Demo 已完成。
12. 机械格式化不等于功能审计；大范围格式化 Commit 必须与业务修改分开解释。
13. 工作结束前同步 `Project.md`、当前 Gate、`开发文档.xlsx` 与必要的 README/状态说明。
