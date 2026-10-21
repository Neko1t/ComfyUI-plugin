# 实现基线与结构

核对日期：2026-10-17。官方稳定标签 `v0.41.3`，提交
`8713616fcc321624e306bbd36be5906203dcb0dc`；内置前端 `1.55.17`。
通过 Git 远端标签及该标签源码核对（GitHub REST 被限流）。验收状态另见测试记录。

## 官方接口

- [V3 扩展](https://docs.comfy.org/custom-nodes/v3_migration)：`ComfyExtension`、`io.ComfyNode`、`define_schema`、`execute` 和 `NodeOutput`。
- [惰性输入](https://docs.comfy.org/custom-nodes/backend/lazy_evaluation)：固定可选端口标记 lazy，`check_lazy_status` 仅请求本次生成启用的输入。复用或恢复已有 jobId 时不请求素材。
- [前端扩展](https://docs.comfy.org/custom-nodes/js/javascript_overview)：`WEB_DIRECTORY` 与 `app.registerExtension`。使用原生 JavaScript 和 DOM widgets，无额外 UI 框架。
- 原生视频采用官方源码 `InputImpl.VideoFromFile`；输入视频通过 `VideoInput.save_to` 编码为 MP4；音频将原生 AUDIO 字典编码为 WAV。
- [VividAI 当前文档](https://vividai.run/docs)：`/v1/models` 返回顶层模型数组和能力字段；`/v1/uploads`、`/v1/generate` 使用文档字段。NDJSON 心跳忽略，恢复仅提交 jobId。

## 模块边界

- `storage.py`：SQLite 事务保存本机连接配置、节点身份、任务意图和素材队列；API 只能返回不含密钥的投影。缓存文件使用 UUID 文件名并检查所有权。
- `client.py`：异步 HTTPX，认证仅发给 API origin；上传 PUT 和结果 GET 使用无认证客户端。提交前持久状态，收到 jobId 立即保存；有 ID 自动重连，无 ID 的异常不得自动重提。
- `service.py`：生成/复用状态机，每个节点串行，成功下载校验后原子入队；失败保留原素材但阻止本次运行继续。
- `media.py`：IMAGE/VIDEO/AUDIO 转换及结果校验；视频输出通过文件租约延迟缓存删除。
- `nodes.py`：四个 V3 节点和 lazy 规则。参数变更不触发付费生成；节点身份及生成意图序列化到工作流。
- `routes.py`、`web/`：本机凭据管理、动态模型、模型能力编辑、历史预览和启用；密钥输入仅存在临时密码框，不进入节点 widget。

## 持久状态

数据默认在 ComfyUI 的系统用户目录下 `__vividai`；可用 `VIVIDAI_DATA_DIR` 指定。凭据是本机文件中的秘密，不随工作流移动。首版面向单人本机 ComfyUI；敏感路由限制本机同源访问。

工作流包含 `node_key`、`generation_token`、配置引用与每模型规则。复制/粘贴节点分配新 node_key；同一工作流重新打开保留身份。

新意图在上传后、提交前记为 submitting。崩溃后若没有 jobId，视为 ambiguous；用户显式选择新的生成意图才可再提交。running 任务保存原始配置引用和参数快照，恢复不使用后来修改的参数。终态失败在显式重新生成或手动启用历史前持续报错。

素材队列默认 3，启用历史只改变选中项与顺序。超出容量先从记录移除，文件有租约时延迟清理；插件仅删除自己缓存目录的文件。
