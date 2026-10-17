// Execute in an isolated ComfyUI browser tab with agent-browser eval -b.
(async () => {
  const { app } = await import("/scripts/app.js");
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const get = (node, name) => node.widgets.find((w) => w.name === name);
  const until = async (predicate) => {
    for (let i = 0; i < 100; i++) {
      if (predicate()) return;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error("browser verification timed out");
  };
  await app.loadGraphData({ nodes: [], links: [], groups: [], config: {}, extra: {}, version: 0.4 });
  const config = LiteGraph.createNode("VividAIConfig");
  const image = LiteGraph.createNode("VividAITextToImage");
  const video = LiteGraph.createNode("VividAITextToVideo");
  const reference = LiteGraph.createNode("VividAIReferenceVideo");
  for (const [index, node] of [config, image, video, reference].entries()) {
    node.pos = [40 + index * 440, 100];
    app.graph.add(node);
  }
  config.connect(0, image, 0); config.connect(0, video, 0); config.connect(0, reference, 0);
  config.widgets.find((w) => w.name === "管理本机 API 配置").callback();
  const dialog = document.querySelector(".vividai-dialog");
  assert(dialog?.open, "credential dialog is open");
  dialog.querySelector('[name="name"]').value = "Browser mock";
  dialog.querySelector('[name="base"]').value = "http://127.0.0.1:8200";
  dialog.querySelector('[name="secret"]').value = "vk_browser_dummy";
  [...dialog.querySelectorAll("button")].find((el) => el.textContent === "保存到本机").click();
  await until(() => !document.querySelector(".vividai-dialog"));
  assert(get(config, "config_ref").value, "configuration reference saved");
  const modelButton = [...image._vividai.root.querySelectorAll("button")]
    .find((el) => el.textContent === "刷新模型");
  modelButton.click();
  await until(() => get(image, "model").options.values?.includes("mock-video-933"));
  assert(get(image, "model").options.values.includes("mock-image"), "all model IDs loaded");
  const modelSelect = image._vividai.root.querySelector('select[aria-label="模型"]');
  assert([...modelSelect.options].some((option) => option.value === "mock-video-933"),
    "visible model dropdown contains server models");
  modelSelect.value = "mock-video-933";
  modelSelect.dispatchEvent(new Event("change"));
  assert(get(image, "model").value === "mock-video-933", "model selection updates workflow field");
  const originalKey = get(reference, "node_key").value;
  get(reference, "model").value = "mock-video-933";
  get(reference, "model_rules").value = JSON.stringify({ "mock-video-933": { max_audios: 0 } });
  get(reference, "model").callback("mock-video-933");
  assert(reference.inputs.filter((i) => /^(image|video|audio)_/.test(i.name)).length === 15,
    "fixed 9/3/3 ports");
  assert(reference.inputs.find((i) => i.name === "audio_1").label.includes("已阻断"),
    "disabled audio port is visible");
  const clone = reference.clone();
  clone.id = -1;
  app.graph.add(clone);
  assert(get(clone, "node_key").value !== originalKey, "cloning creates an independent identity");
  assert(get(clone, "generation_token").value === "", "clone has no generation intention");
  app.graph.remove(clone);
  const regen = [...reference._vividai.root.querySelectorAll("button")]
    .find((el) => el.textContent === "下次运行重新生成");
  regen.click();
  const token = get(reference, "generation_token").value;
  assert(token.length === 36, "regeneration marks an intent");
  const workflow = app.graph.serialize();
  const prompt = await app.graphToPrompt();
  assert(!JSON.stringify(workflow).includes("vk_browser_dummy"), "workflow has no API key");
  assert(!JSON.stringify(prompt).includes("vk_browser_dummy"), "API prompt has no API key");
  await app.loadGraphData(workflow);
  const reloaded = app.graph._nodes.find((n) => get(n, "node_key")?.value === originalKey);
  assert(reloaded, "workflow reload retains node identity");
  assert(get(reloaded, "generation_token").value === token, "workflow retains marked intent");
  assert(JSON.parse(get(reloaded, "model_rules").value)["mock-video-933"].max_audios === 0,
    "per-model rules survive workflow export");
  const liveImage = app.graph._nodes.find((n) => n.comfyClass === "VividAITextToImage");
  get(liveImage, "model").value = "mock-image";
  get(liveImage, "prompt").value = "browser image";
  get(liveImage, "model").callback("mock-image");
  const save = LiteGraph.createNode("SaveImage"); app.graph.add(save);
  liveImage.connect(0, save, 0);
  await app.queuePrompt(0, 1);
  await until(() => liveImage._vividai.state?.history.length === 1);
  const firstMaterial = liveImage._vividai.state.selected;
  assert(liveImage._vividai.history.querySelector("img"), "image preview is rendered");
  get(liveImage, "prompt").value = "browser second";
  [...liveImage._vividai.root.querySelectorAll("button")]
    .find((el) => el.textContent === "下次运行重新生成").click();
  await app.queuePrompt(0, 1);
  await until(() => liveImage._vividai.state?.history.length === 2);
  [...liveImage._vividai.history.querySelectorAll("button")]
    .find((el) => el.textContent === "启用此素材").click();
  await until(() => liveImage._vividai.state.selected === firstMaterial);
  assert(get(liveImage, "prompt").value === "browser second", "history activation retains current prompt");
  window.vividaiBrowserReport = {
    checks: ["four node UIs", "secret dialog", "dynamic models", "fixed/disabled ports",
      "independent clone", "regeneration marker", "secret-free workflow/API prompt",
      "reload identity and per-model rules", "UI queue execution", "history preview and activation"],
    passed: true,
  };
  return window.vividaiBrowserReport;
})();
