# 更新记录

## 未发布

- 按 VividAI 当前接口要求，将视频时长设为默认必填。
- 新建视频节点默认使用 6 秒，并在缺少时长时于本地给出明确提示。

## 0.1.5 - 2026-10-17

- 将节点入口改为静态 `NODE_CLASS_MAPPINGS` 和 `NODE_DISPLAY_NAME_MAPPINGS`。
- 保留 V3 `comfy_entrypoint`，兼容 ComfyUI 运行时与 Registry 节点详情提取。
- 兼容 ComfyUI 文件加载器在无父包场景下导入插件。
