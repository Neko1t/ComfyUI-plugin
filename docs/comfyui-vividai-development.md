# ComfyUI 扩展开发与 VividAI 视频接入调研

> 历史调研记录，不是当前实现依据。本文引用的 Context7 VividAI 索引已过时，旧 `/v1/videos` 和 `/v1/images/generations` 协议不用于本项目。当前确认规格见 [specification.md](specification.md)，最新协议研究见 [../findings.md](../findings.md)。

调研日期：2026-10-17。通过 Context7 查阅 ComfyUI 官方文档及用户提供的 VividAI 文档；以下区分文档事实、实现建议和待确认事项。本阶段仅整理开发依据，尚未实现节点或调用付费生成接口。

## 1. 开发形态

目标适合做成安装在 `ComfyUI/custom_nodes/` 下的 Python 自定义节点包，让用户直接在工作流中调用 VividAI 生成视频。

| 需求 | 对应扩展机制 |
| --- | --- |
| 定义输入、参数、输出，调用远程视频服务 | Python 自定义节点 |
| 添加设置项、按钮、任务状态等界面交互 | 可选的 JavaScript 前端扩展 |
| 向前端提供模型列表、连接测试等接口 | 按需增加 ComfyUI 后端路由 |
| 分享工作流、接到原生视频保存节点 | 保持节点 ID 稳定，使用原生数据类型 |

基础版本可以先用标准节点控件完成。前端扩展按实际交互需要加入。

## 2. 节点 API：V3 与 V1

官方文档明确：旧版 V1 仍受支持，新节点可以使用现代 V3 schema，未来节点功能扩展会加入 V3。这里的 V3 是节点定义机制的版本。

| 项目 | V1 | V3 |
| --- | --- | --- |
| 节点定义 | 普通 Python 类 | 继承 `io.ComfyNode` |
| 输入与输出 | `INPUT_TYPES`、`RETURN_TYPES` | `define_schema()` 返回 `io.Schema` |
| 执行函数 | `FUNCTION` 指定方法名 | `execute()` 类方法 |
| 返回值 | 输出元组，可包含 UI 字典 | `io.NodeOutput` |
| 包入口 | `NODE_CLASS_MAPPINGS` 等 | `comfy_entrypoint()` 返回 `ComfyExtension` |
| 缓存指纹 | `IS_CHANGED` | `fingerprint_inputs` |

建议新项目优先采用 V3，先确定需要支持的 ComfyUI 版本。官方示例允许从 `comfy_api.latest` 导入，也提供版本化 API；最终导入方式与最低版本需要根据目标安装环境确定。

V3 支持 `async def execute(...)`，适合网络请求和轮询等待。节点以类方法执行，不应依赖节点实例的 `__init__` 保存任务状态。任务恢复信息应明确传递或持久化。

## 3. 官方开发流程

1. **确定运行环境与兼容范围。** 确认 ComfyUI 版本、安装方式及实际使用的 Python。依赖必须安装到该 Python 环境中。
2. **建立节点包。** 在 `custom_nodes/<节点包目录>/` 中放置 `__init__.py`、节点代码、依赖声明和说明文档。也可参考官方扩展模板组织项目。
3. **定义节点 schema。** 为每个节点设置带包前缀的唯一 ID、显示名、分类、说明、输入和输出；尽早稳定对外 ID 与字段名。
4. **实现并注册。** V3 实现 `define_schema()`、`execute()`，在 `ComfyExtension.get_node_list()` 中返回节点类，并导出 `comfy_entrypoint()`。
5. **安装与加载。** 将节点包放入目标 ComfyUI 的 `custom_nodes`，安装其依赖并重启服务，查看启动日志，确认没有导入错误。修改前端资源后刷新页面。
6. **跑通完整工作流。** 将生成节点接到原生视频输出节点；ComfyUI 会从输出节点追溯依赖，因此只有孤立的普通计算节点不构成完整验证流程。
7. **补充交互与示例。** 根据需要添加设置、事件、路由，并提供可导入的示例工作流。
8. **打包发布。** 完成 README、许可证、依赖和 `pyproject.toml` 元信息；需要公开分发时再接入 Comfy Registry、版本号与发布流程。

Windows Portable 的官方依赖安装示例，从 Portable 根目录执行：

```powershell
.\python_embeded\python.exe -m pip install -r .\ComfyUI\custom_nodes\<节点包目录>\requirements.txt
```

该命令仅说明 Portable 环境；Desktop 或其他安装方式需要找到各自实际使用的解释器。

## 4. 前端扩展方式

官方文档中的基本机制：

1. Python 包导出 `WEB_DIRECTORY`，例如指向 `./web/js`。
2. 在该目录放置 JavaScript 文件。
3. 导入 ComfyUI 的 `app`，通过 `app.registerExtension(...)` 注册唯一名称和所需 hooks。

例如可用于增加设置项、展示任务状态或添加按钮。后端与前端可通过自定义事件通信；需要 HTTP 接口时，后端注册路由，前端使用 `api.fetchApi(...)` 调用。

这些界面扩展需要使用目标版本支持的接口。核心生成流程应能脱离额外界面增强独立执行。

## 5. VividAI 文档中已确认的接口

文档：[https://vividai.run/docs](https://vividai.run/docs)。示例 API Base URL 为 `https://vividai.run/v1`，鉴权为 `Authorization: Bearer <API_KEY>`。

| 操作 | 方法与路径 | 文档说明 |
| --- | --- | --- |
| 获取模型列表 | `GET /v1/models` | 返回可用模型 |
| 提交视频任务 | `POST /v1/videos` | 异步创建，返回任务 `id` 和初始 `queued` 状态 |
| 查询任务 | `GET /v1/videos/{id}` | 查询当前任务状态 |
| 下载成品 | `GET /v1/videos/{id}/content` | 完成后返回 MP4 二进制数据 |

文档中的文生视频请求示例：

```json
{
  "model": "grok-video",
  "prompt": "a paper boat sailing down a rainy street",
  "seconds": "6",
  "size": "1280x720"
}
```

文档示例每 5 秒查询一次，直到 `completed` 或 `failed`。这只是示例轮询策略，实现时仍需设置请求超时、整体等待时限和中断处理。

文档还提到 `input_reference` 文件输入，某些模型（例如 Runway）要求参考图。各模型支持的时长、分辨率、输入方式应单独核实，不能因接口兼容就假定所有模型参数相同。

文档列出的常见错误包括：`400` 参数不符合要求、`401` Key 无效、`402` 余额不足、`404` 模型未知或任务不存在、`409` 视频尚未完成、`429` 账号并发已满、`503` 上游繁忙。

## 6. 建议的节点与代码组织

第一阶段优先打通：**输入参数 → 提交任务 → 轮询 → 下载 MP4 → 输出原生 VIDEO → Save Video**。

| 建议节点 | 职责 | 优先级 |
| --- | --- | --- |
| VividAI 文生视频 | 选择模型，提交、等待并输出视频 | 第一阶段 |
| VividAI 图生视频 | 接收 `IMAGE`，编码并按服务约定上传参考图 | 核实文件输入协议后 |
| VividAI 获取已有任务 | 输入任务 ID，查询并获取视频，支持恢复流程 | 第一阶段后续 |
| VividAI 模型专用节点 | 为参数差异较大的模型提供清晰的专用控件 | 按模型需求加入 |

普通用户可使用完整生成节点；提交、查询和下载在服务代码中拆分，方便后续增加高级节点。模型专用节点复用同一套鉴权、请求、轮询和下载逻辑。

建议目录结构，实际名称待项目命名确定：

```text
<节点包>/
  __init__.py             # V3 扩展入口
  nodes/                  # ComfyUI schema 与输入输出转换
  services/
    client.py             # 鉴权、HTTP、错误转换
    video_tasks.py        # 提交、查询、等待、结果下载
    capabilities.py       # 已确认的模型能力与参数约束
  config.py               # 后端凭据与连接配置
  web/js/                 # 需要时加入的前端扩展
  example_workflows/      # 可导入工作流
  tests/                  # HTTP 模拟与任务生命周期测试
  requirements.txt
  pyproject.toml
  README.md
```

## 7. 需要落实的关键行为

- **视频输出。** 下载后的文件应包装为 ComfyUI 原生视频对象，例如官方示例使用的 `VideoFromFile`，并声明 `VIDEO` 输出。URL、文件路径字符串本身并不是视频对象。优先使用文件方式管理较大的 MP4，再接原生 Save Video；需要帧处理时再增加解码路径。
- **素材输入。** ComfyUI 的 `IMAGE` 是图像数据，需转换为 API 接受的文件或其他约定格式；本地路径不能直接作为远程服务可读取的素材地址。
- **凭据。** 建议从后端环境变量或本地配置读取 Key，工作流只保存配置引用。避免 Key 进入工作流、输出视频元数据和日志。
- **认证边界。** ComfyUI 官方 Partner/API Nodes 的 ComfyOrg token 和第三方 VividAI Key 属于不同认证体系。不能照搬官方节点的认证字段；`is_api_node` 等标记是否适用，需结合目标版本的行为核实。
- **缓存与计费。** ComfyUI 会缓存节点结果。应明确用户如何重新生成，并区分服务支持的生成 seed 与仅用于触发执行的请求序号。`fingerprint_inputs` 返回固定 `True` 不代表每次重跑。
- **重试。** 查询和下载可以按错误性质有限重试；创建任务超时可能意味着远端已受理，不能直接反复提交。先核实幂等支持，并保留已经取得的任务 ID。
- **中断。** 在网络等待和轮询之间响应本地中断。停止本地等待与取消远程任务是两件事，远程取消能力尚需文档确认。
- **任务恢复。** 取得任务 ID 后及时记录。下载失败、等待超时或界面刷新后，应能通过已有 ID 恢复，避免重新生成。
- **状态提示。** 展示排队、生成、下载、失败等真实阶段；只有服务返回实际进度时才显示对应百分比。
- **模型能力。** 用模型能力约束时长、分辨率和参考图要求。`GET /v1/models` 能列出模型，不应假定它一定提供全部参数约束。

## 8. 后续实现前仍需确认

1. 用户目标 ComfyUI 的版本与安装方式，据此确定 V3 API 和视频类型兼容范围。
2. 第一批接入模型及各模型允许的时长、分辨率、参考图限制。
3. 视频参考图的准确 multipart 字段、请求编码及是否接受其他输入形式。
4. 状态响应的完整字段、错误结构、是否包含进度和结果过期信息。
5. 创建请求的幂等约定、远程取消接口，以及任务和成品的保留期限。

这些内容不能仅根据“OpenAI 兼容”推断。当前尚未进行鉴权请求或付费生成验证。

## 9. 验证路径

实现时先用模拟 HTTP 响应覆盖：成功、排队转失败、鉴权失败、并发限制、创建响应丢失、等待超时、本地中断、下载失败与已有任务恢复。然后在目标 ComfyUI 中验证节点导入、文生视频到 Save Video 的完整链路，以及工作流保存和重新载入。

## 10. 来源

- [ComfyUI 自定义节点概述](https://docs.comfy.org/custom-nodes/overview)
- [ComfyUI 节点开发 walkthrough](https://docs.comfy.org/custom-nodes/walkthrough)
- [V3 Migration 官方说明](https://docs.comfy.org/custom-nodes/v3_migration)
- [后端节点与执行、缓存机制](https://docs.comfy.org/custom-nodes/backend/server_overview)
- [JavaScript 扩展机制](https://docs.comfy.org/custom-nodes/js/javascript_overview)
- [JavaScript 设置项](https://docs.comfy.org/custom-nodes/js/javascript_settings)
- [服务端通信与自定义消息](https://docs.comfy.org/development/comfyui-server/comms_messages)
- [服务端与自定义路由](https://docs.comfy.org/development/comfyui-server/comms_routes)
- [原生 Save Video 节点](https://docs.comfy.org/built-in-nodes/SaveVideo)
- [Comfy Registry 发布流程](https://docs.comfy.org/registry/publishing)
- [官方 Python 扩展模板](https://github.com/Comfy-Org/cookiecutter-comfy-extension)
- [VividAI 接口文档](https://vividai.run/docs)
