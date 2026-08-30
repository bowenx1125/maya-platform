# Maya Demo v0.1 编码前合同包

状态：`C01-C12 BASELINE FROZEN / WAVE 2 MANUAL-ACCEPTANCE DELTA FROZEN — SOL HIGH G0-S PASS / G1 AUTHORIZED`
合同版本：`g0-2026-08-28.6-manual-acceptance-delta`（历史已签基线：`g0-2026-08-27.5`）
权威来源：`/Users/xubosmell/Desktop/Maya/Project.md` 第 0、5、8 节

## 用途

本目录把已经冻结的产品边界翻译成可执行的编码合同。它不是产品源码。C01-C11 审计、C12 最终确认和用户明确授权已于 2026-08-26 19:06 全部满足，因此编码门禁已经打开；实现仍只能按模块 Gate 推进。

## 文件

| 合同 | 内容 | 文件 | 当前状态 |
| --- | --- | --- | --- |
| C01 | Scope、页面地图、关键线框 | `G0_CONTRACT.md` | FROZEN |
| C02 | ERD、约束、文件生命周期 | `G0_CONTRACT.md` | FROZEN |
| C03 | OpenAPI v0.1 | `openapi-v0.1.yaml` | FROZEN |
| C04 | API/对象权限矩阵 | `G0_CONTRACT.md` | FROZEN |
| C05 | 五状态域状态机 | `G0_CONTRACT.md` | FROZEN |
| C06 | WebSocket 事件 Schema | `G0_CONTRACT.md` | FROZEN |
| C07 | 错误、重试、幂等矩阵 | `G0_CONTRACT.md` | FROZEN |
| C08 | Provider、密钥和文件安全 | `G0_CONTRACT.md` | FROZEN |
| C09 | 验收数据与 E2E | `G0_CONTRACT.md` | FROZEN |
| C10 | 模块依赖、Gate、所有权 | `G0_CONTRACT.md` | FROZEN |
| C11 | 全局冲突审计 | `C11_GLOBAL_AUDIT.md` | FROZEN |
| C12 | 用户最终总确认 | `C12_REVIEW.md` + `C12_VISUAL_REVIEW.md` + 四类视觉稿确认 + 用户明确编码授权 | FROZEN / CODING AUTHORIZED 2026-08-26 19:06 |
| Preflight | 编码授权前活动文档、共享工作簿、环境与风险复核 | `PRE_CODE_PREFLIGHT.md` | PASS |

状态只允许：`PENDING → DRAFTED → AUDITED → FROZEN`。

## 禁止直接复制代码

- 参考项目只用于理解交互、状态机、模块边界和测试思路；
- 禁止直接复制粘贴实现代码、整段改名、整仓裁剪或继承外部领域模型；
- 所有 Maya 实现必须从本合同的 DTO、状态机、权限和验收测试重新设计；
- 禁止引入参考仓库的任何实现代码片段，没有例外；可以正常使用依法引入的第三方依赖包，但不得从其仓库复制源码；
- 合同审计只检查“设计是否合理”，不能把参考仓库的现有实现当成 Maya 已经完成。

## 合同变更

1. 先修改 `Project.md` 当前契约；
2. 标记受影响的 C01-C11 为 `DRAFTED`；
3. 更新合同与 OpenAPI；
4. 运行 C11 冲突审计；
5. 重新取得对应 Gate 的审计通过。
