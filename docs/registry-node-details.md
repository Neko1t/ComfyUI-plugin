# Registry 节点详情排查（2026-10-17）

本地 ComfyUI 能加载四个节点，并不表示 Registry 已完成 `comfy_nodes` 提取。Registry 的节点包版本状态与节点详情记录是独立数据。

## 已核实状态

通过 `GET /versions?nodeId=comfyui-vividai&include_status_reason=true` 和各版本的 `GET /nodes/comfyui-vividai/versions/{version}/comfy-nodes` 检查：

| 版本 | 版本状态 | `comfy_node_extract_status` | `comfy_nodes` |
| --- | --- | --- | --- |
| 0.1.0 | `NodeVersionStatusFlagged` | `pending` | 空 |
| 0.1.1 | `NodeVersionStatusFlagged` | `pending` | 空 |
| 0.1.2 | `NodeVersionStatusPending` | `pending` | 空 |

0.1.0/0.1.1 的 `status_reason` 是安全扫描结果，包含八条 `info` 级发现。其中五条来自仅供开发使用的 `uv.lock`、`tests/` 和 `tools/`；其余来自运行时的环境变量读取、网络操作与 SQLite 持久化。`uv.lock` 中被识别为比特币地址的是依赖包下载 URL 的哈希片段。不要为了避开扫描而删除用户要求的本机持久化功能。

0.1.2 的发布归档已包含根目录 `__init__.py`、四节点映射以及节点实现；本地使用当前 ComfyUI API 生成四个 `GET_NODE_INFO_V1()` 详情均成功。仅添加 `NODE_CLASS_MAPPINGS` 尚不能解释或修复 Registry 提取状态持续为 `pending` 的问题。

## 修复与验收步骤

1. 使用官方支持的 `.comfyignore` 排除 Git 跟踪的开发文件。发布归档仍须包含 `__init__.py`、`vividai/`、`web/`、`pyproject.toml` 和安装所需的 `requirements.txt`。
2. 旧版本不可修改。准备一个新版本发布排除开发文件的归档，并检查该版本的 `status`、`status_reason`、`comfy_node_extract_status`。
3. 若仍因 `vividai/runtime.py` 或 `vividai/storage.py` 被标记，向 Registry 维护方说明：环境变量用于选择本机数据目录、SQLite 用于保存本机 API 配置和生成历史、网络请求用于 VividAI API。保留扫描原因和版本链接供审核；不要通过改写代码隐藏这些行为。
4. 仅当新版本状态允许使用、提取状态为 `completed`，且 `GET /nodes/comfyui-vividai/versions/{version}/comfy-nodes` 返回四条节点记录时，才确认详情页数据问题已修复。如果版本已可用而提取失败，再调查 Registry 提取环境与节点导入兼容性。

官方依据：[发布与 `.comfyignore`](https://docs.comfy.org/registry/publishing#exclude-files-with-comfyignore)、[Registry 安全规范](https://docs.comfy.org/registry/standards)、[版本状态 API](https://docs.comfy.org/registry/api-reference/registry/list-all-node-versions-given-some-filters)、[`comfy_nodes` 列表 API](https://docs.comfy.org/registry/api-reference/registry/list-comfy-nodes-for-node-version)、[V3 节点入口](https://docs.comfy.org/custom-nodes/v3_migration)。
