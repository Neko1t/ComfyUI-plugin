# 验收与复现

日期：2026-10-17。Windows，本机 CPU 模式；CPython 3.13.5。

官方源码基线为 ComfyUI `v0.41.3` / commit `8713616fcc321624e306bbd36be5906203dcb0dc`，前端 `1.55.17`。开发依赖由 uv 管理；宿主验收额外安装官方 requirements，实际测试 torch 为 `2.14.1+cpu`、PyAV `19.0.1`。集成依赖未作为插件运行依赖锁定，用户继续使用自己的 ComfyUI 环境。

## 自动测试

- 存储：凭据投影、节点隔离、重启持久化、队列置顶与淘汰、文件租约、缓存路径限制、崩溃孤立文件清理。
- HTTP：真实回环 HTTP 上传/NDJSON/下载，无认证头泄漏到素材请求，流中断后同 jobId 恢复，无 ID 时不重提，错误中的密钥脱敏。
- 状态机：修改参数仍复用、显式生成、重启恢复原参数、失败停止与手动启用历史。
- 路由：同源/本机限制、凭据不返回、视频 Range 请求和文件租约。
- 官方 API：直接导入实际 ComfyUI，无伪造 schema，验证四节点注册、固定 lazy 端口和原生 VIDEO 生命周期。

最终测试计数和端到端结果在下方「最终结果」记录。

## 整张工作流和浏览器测试

准备隔离的 ComfyUI 测试根目录，例如 `.local/comfy`，将本项目链接/复制到其 `custom_nodes/vividai`。只在该测试目录将 `tools/e2e_nodes` 链接/复制为 `custom_nodes/vividai_test_guards`，它们是用于证明上游未执行的故意报错节点，不用于正式安装。

安装官方测试依赖（使用项目 `.venv` 的绝对解释器路径），在不同终端运行：

```powershell
git clone --depth 1 --branch v0.41.3 https://github.com/Comfy-Org/ComfyUI.git .comfyui-dev
uv pip install --python .venv/Scripts/python.exe -r .comfyui-dev/requirements.txt
```

```powershell
uv run --no-sync python tools/mock_provider.py
```

```powershell
$env:VIVIDAI_DATA_DIR=(Join-Path (Get-Location) '.local/runtime')
uv run --no-sync python .comfyui-dev/main.py --cpu --base-directory .local/comfy --listen 127.0.0.1 --port 8199 --disable-auto-launch --offline
```

```powershell
uv run --no-sync python tools/e2e_verify.py
```

模拟服务仅监听 `127.0.0.1:8200`。验收脚本访问测试实例 `8199`，以虚假 Key 创建测试配置；验证 IMAGE/VIDEO 接官方保存节点、参数修改复用、显式生成、流断线恢复、失败停止、历史启用、图片/视频/音频编码上传、禁用端口及缓存模式跳过故意报错的上游。

浏览器测试：在隔离浏览器打开测试实例，使用 agent-browser 执行 `tools/browser_verify.js`（base64 eval 可避免 PowerShell 引号问题）：

```powershell
agent-browser --session vividai-test open http://127.0.0.1:8199
$encoded=[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path (Get-Location) 'tools/browser_verify.js')))
agent-browser --session vividai-test eval -b $encoded
```

该脚本会创建空白测试工作流并添加节点，验证真实下拉操作、临时密码输入、工作流/API prompt 无 Key、复制节点身份、重开持久化、UI 排队运行和历史启用后保留当前参数。运行前请使用专门的测试标签页。

## 最终结果

- Python：**18 passed**（包含 2 项直接导入官方 ComfyUI 的集成测试）。
- Ruff 检查、格式检查与 JavaScript 语法检查通过。
- 真实 ComfyUI 工作流 + 回环模拟服务：**10 项检查通过**；测试包含 6 次显式/初次提交、1 次同任务重连、4 次素材上传；修改参数、启用历史、缓存复用均未额外提交。
- 浏览器：**10 项检查通过**，包括实际 DOM 下拉操作、凭据保存、工作流导出/重开、复制身份、UI 排队生成和历史激活；无 JavaScript 错误。
- 三份示例由实际前端序列化生成，导入后保留配置引用字段、固定端口和保存节点连线。它们不含密钥或具体服务模型。
- 首次界面测试发现文本 widget 改 type 无法生成可用下拉框，已修正为原生 DOM select，并通过真实 change 事件和工作流运行复验。

## 验证边界

未取得真实 VividAI Key，因此没有真实付费任务验证；模拟测试只能证明客户端与已读取文档的一致性。没有 Linux/macOS 或 GPU 测试。上架 Registry/Manager、推送 Git 远端和对外发布不在本轮执行范围。
