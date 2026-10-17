# ComfyUI VividAI

VividAI 本机持久化节点包，MIT 开源。兼容基线：**ComfyUI v0.41.3 / 前端 1.55.17**。

提供 VividAI 配置、文生图、文生视频、参考素材生视频四个节点。图片输出为原生 `IMAGE`，视频为原生 `VIDEO`，可连接官方保存节点。

## 安装

将本项目放到 `ComfyUI/custom_nodes/comfyui-vividai`，不要只复制 `vividai` 子目录。
在该目录打开终端，使用 **ComfyUI 实际运行的 Python** 安装依赖，然后重启 ComfyUI：

```powershell
uv pip install --python "C:\你的ComfyUI环境\Scripts\python.exe" -r requirements.txt
```

Windows 便携版通常使用其 `python_embeded\python.exe`；桌面版使用自身环境，路径以实际安装为准。
uv 可按 [官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装。也可在已有 Python 中执行 `python -m pip install uv`，然后用 `python -m uv` 替代命令 `uv`。

项目自己的 `.venv` 用于开发测试；ComfyUI 仍需在自己的解释器中安装本插件依赖。插件不要求额外安装 PyTorch，使用宿主已有版本。

## 第一次使用

1. 用 `http://127.0.0.1:8188` 或 `http://localhost:8188` 打开 ComfyUI，添加 **VividAI 配置**。
2. 点击「管理本机 API 配置」，输入配置名、`https://vividai.run` 和 API Key；保存后选择本机配置。
3. 添加生成节点并连接配置，点击「刷新模型」，选择服务返回的模型。三个生成节点均展示全部模型，由用户选择对应生成方式。
4. 填写提示词、清晰度、比例，展开「当前模型能力配置」按服务模型规则调整。新模型的参考素材默认上限为 **933**。默认清晰度/时长只是可编辑模板，不代表所有模型都支持。
5. 文生图接 `SaveImage`；视频接官方 `SaveVideo`。正常运行工作流，首次生成一份素材。

[examples](examples/) 内有三个可直接导入的工作流模板。导入后先保存本机配置、刷新模型并填写参数；模板不预置真实模型 ID 或密钥。参考示例连接一张 `EmptyImage`，可替换成自己的图片，也可连接原生 `VIDEO` 和 `AUDIO` 输入。

## 生成与历史

- **默认复用选中素材。** 修改提示词、模型、能力规则或参考素材，均不会自动创建新任务。
- 「下次运行重新生成」只标记当前节点；下一次正常运行才生成一份。未连接输出分支的节点不会单独执行。
- 每个节点默认保留最近 **3** 份素材，`history_capacity` 可设为 1–100。
- 历史中点击「启用此素材」会将它移到队头，只切换输出，保留当前提示词和参数。再运行即可把选中素材传给下游。
- 失败会停止本次工作流，旧素材保留，需手动启用；不会静默用旧结果代替失败任务。
- 超出队列的插件缓存会被清理；正在使用的视频延迟删除。通过保存节点另存到输出目录的文件不受清理影响。
- 同一工作流重开保留节点历史；复制/粘贴节点产生新身份。把工作流移到另一台电脑时，需要重新建立本机配置和生成素材。

参考素材节点固定提供 **9 个图片、3 个视频、3 个音频**编号端口，每口一份素材。能力配置可以降低启用数量；禁用端口保留连线，并惰性阻止该分支的上游计算、编码和上传。其他输出分支仍可独立执行同一上游。ComfyUI 在执行前仍会验证整个相关图的端口类型与输入合法性，禁用端口不能绕过图验证。

图片端口不接受多图批次；音频不接受多份批次。图片转 PNG（≤20 MB），视频转 MP4、音频转 WAV（各≤40 MB），按图片编号→视频编号→音频编号提交。视频比例受服务固定限制，仅支持 `16:9` / `9:16`。时长填 `0` 表示不发送；模型要求时长时须填写，规则中可设置必填、范围及可选值。

## 任务恢复与本机数据

拿到 jobId 后立即持久保存，断线或重启后运行同一节点会重连原任务。单次等待最长 15 分钟，达到上限保留待恢复状态。恢复不重新上传素材，也不应用后来修改的参数。

尚未收到 jobId 的提交中断会标记为「状态不明确」，禁止自动重提。请先到 VividAI 核实，再决定是否显式标记新生成。本地停止等待不等于取消远程任务；服务文档没有取消接口。

默认数据目录为 `ComfyUI/user/__vividai`（遵循自定义用户目录），可用 `VIVIDAI_DATA_DIR` 指定。目录包含 `state.sqlite3` 和缓存；备份/迁移整个目录可保留记录。**本机数据库包含 API Key，属于敏感文件**，不应随源码、工作流或公开备份分享。首版面向单人本机实例，同一数据目录不要由多个 ComfyUI 进程同时使用；配置和历史管理路由仅允许 localhost 同源访问。

API Key 只通过独立密码框保存；工作流、API prompt 与成品元数据仅含配置引用。能力规则保存在节点的工作流字段中；不要手工修改隐藏的 `node_key` / `generation_token`。

## 开发与验证

```powershell
uv sync --locked
uv run pytest
uv run ruff check .
```

普通测试不需要 ComfyUI 或 VividAI 密钥。实际 ComfyUI API 测试另需准备宿主依赖与源码：

```powershell
$env:COMFYUI_PATH="C:\开发环境\ComfyUI"
uv run --no-sync pytest tests/test_nodes.py
```

完整复现步骤和实际结果见 [验收记录](docs/verification.md)。Windows 下已用模拟服务验证实际工作流及浏览器界面；**尚未进行真实 VividAI 付费生成、Linux/macOS 或 GPU 验收**。

设计依据：[确认规格](docs/specification.md)、[接口与架构](docs/implementation.md)、[VividAI 文档](https://vividai.run/docs)、[ComfyUI V3 文档](https://docs.comfy.org/custom-nodes/v3_migration)。
