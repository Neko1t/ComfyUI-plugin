import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const GENERATORS = new Set(["VividAITextToImage", "VividAITextToVideo", "VividAIReferenceVideo"]);
const ALL = new Set(["VividAIConfig", ...GENERATORS]);
const DEFAULT_RULE = {
  max_images: 9, max_videos: 3, max_audios: 3,
  min_images: 0, min_videos: 0, min_audios: 0,
  qualities: ["720p", "1080p", "1K", "2K"], ratios: ["16:9", "9:16", "1:1"],
  duration_required: true, duration_min: 1, duration_max: 30, durations: [],
};
let loadingWorkflow = false;
let profiles = [];
const widget = (node, name) => node.widgets?.find((w) => w.name === name);
const value = (node, name) => widget(node, name)?.value;

async function request(path, options = {}) {
  const response = await api.fetchApi(`/vividai${path}`, {
    ...options, headers: { "Content-Type": "application/json", ...options.headers },
  });
  let data;
  try { data = await response.json(); } catch { throw new Error(`本机请求失败 ${response.status}`); }
  if (!response.ok) throw new Error(data.error || `本机请求失败 ${response.status}`);
  return data;
}

function element(tag, text, className) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
}

function button(label, handler) {
  const el = element("button", label);
  el.type = "button";
  el.onclick = async (event) => {
    event.stopPropagation();
    el.disabled = true;
    try { await handler(); } finally { el.disabled = false; }
  };
  return el;
}

function setValue(node, name, next) {
  const w = widget(node, name);
  if (w) w.value = next;
  app.graph?.setDirtyCanvas(true, true);
}

function hide(w) {
  if (!w) return;
  w.hidden = true;
  w.type = "converted-widget";
  w.computeSize = () => [0, -4];
  w.draw = () => {};
}

function combo(w, values, labels = {}) {
  if (!w) return;
  const all = [...new Set([w.value, ...values].filter(Boolean))];
  w.options = { ...w.options, values: all };
  w.options.getOptionLabel = (id) => labels[id] || id;
  if (w._vividaiSelect) {
    const select = w._vividaiSelect;
    select.replaceChildren();
    if (!w.value || !all.length) select.append(new Option("请选择", ""));
    for (const id of all) select.append(new Option(labels[id] || id, id));
    select.value = w.value;
  }
}

function bindSelect(node, name, parent, label) {
  const w = widget(node, name);
  const row = element("label", null, "vividai-field");
  row.append(element("span", label));
  const select = element("select"); select.setAttribute("aria-label", label);
  select.onchange = () => {
    setValue(node, name, select.value);
    w.callback?.(select.value);
  };
  w._vividaiSelect = select;
  row.append(select); parent.append(row); hide(w);
  return select;
}

function rules(node) {
  const parsed = JSON.parse(value(node, "model_rules") || "{}");
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
}

function currentRule(node) {
  try { return { ...DEFAULT_RULE, ...rules(node)[value(node, "model")] }; }
  catch { return { ...DEFAULT_RULE }; }
}

function providerRule(model) {
  const rule = { ...DEFAULT_RULE, _source: "provider" };
  if (Array.isArray(model.qualities)) rule.qualities = model.qualities;
  for (const [field, name, bound] of [
    ["refImages", "max_images", 9], ["refVideos", "max_videos", 3],
    ["refAudios", "max_audios", 3],
  ]) rule[name] = Math.min(bound, Math.max(0, Number(model[field] ?? 0)));
  const duration = model.duration;
  if (duration?.mode === "fixed") {
    rule.duration_required = true;
    rule.duration_min = rule.duration_max = duration.seconds;
    rule.durations = [duration.seconds];
    rule._duration_mode = "fixed";
  } else if (duration?.mode === "range") {
    rule.duration_required = true;
    rule.duration_min = duration.min; rule.duration_max = duration.max;
    rule.durations = [];
    rule._duration_mode = "range";
  } else if (duration?.mode === "options" && Array.isArray(duration.options) && duration.options.length) {
    rule.duration_required = true;
    rule.duration_min = Math.min(...duration.options);
    rule.duration_max = Math.max(...duration.options);
    rule.durations = duration.options;
    rule._duration_mode = "options";
  }
  return rule;
}

function profileRef(node) {
  const input = node.inputs?.find((i) => i.name === "config");
  const link = input?.link != null ? app.graph?.links[input.link] : null;
  const config = link ? app.graph.getNodeById(link.origin_id) : null;
  return config?.comfyClass === "VividAIConfig" ? value(config, "config_ref") : "";
}

function setStatus(node, message, error = false) {
  const status = node._vividai?.status;
  if (status) { status.textContent = message; status.dataset.error = String(error); }
}

function syncRule(node) {
  const rule = currentRule(node);
  if (rule._source === "provider" && rule.qualities?.length
    && !rule.qualities.includes(value(node, "quality"))) {
    setValue(node, "quality", rule.qualities[0]);
  }
  if (node.comfyClass !== "VividAITextToImage" && rule._source === "provider") {
    const seconds = Number(value(node, "duration"));
    if (rule._duration_mode === "fixed" && seconds !== rule.duration_min) {
      setValue(node, "duration", rule.duration_min);
    } else if (rule.duration_required && (seconds < rule.duration_min || seconds > rule.duration_max
      || (rule.durations.length && !rule.durations.includes(seconds)))) {
      const preferred = rule.durations.length ? rule.durations[0]
        : Math.max(rule.duration_min, Math.min(6, rule.duration_max));
      setValue(node, "duration", preferred);
    }
  }
  combo(widget(node, "model"), widget(node, "model")?.options.values || []);
  combo(widget(node, "quality"), rule.qualities || []);
  combo(widget(node, "ratio"), rule.ratios || []);
  for (const input of node.inputs || []) {
    const match = /^(image|video|audio)_(\d+)$/.exec(input.name);
    if (match) {
      const enabled = Number(match[2]) <= rule[`max_${match[1]}s`];
      input.label = enabled ? input.name : `${input.name}（已阻断）`;
      input.color_on = enabled ? undefined : "#6b7280";
      input.color_off = enabled ? undefined : "#6b7280";
    }
  }
  const editor = node._vividai?.ruleEditor;
  if (editor) editor.replaceChildren(buildRuleForm(node, rule));
  app.graph?.setDirtyCanvas(true, true);
}

function buildRuleForm(node, rule) {
  const form = element("div", null, "vividai-rules");
  form.append(element("p", `当前模型：${value(node, "model") || "请先选择模型"}`));
  const fields = [
    ["qualities", "清晰度列表（逗号分隔，留空不限制）", "list"],
    ["ratios", "比例列表（逗号分隔，留空不限制）", "list"],
    ["duration_required", "必须提交时长", "checkbox"],
    ["duration_min", "最短时长（秒）", "number", 1, 3600],
    ["duration_max", "最长时长（秒）", "number", 1, 3600],
    ["durations", "时长可选值（逗号分隔，留空使用范围）", "numbers"],
  ];
  if (node.comfyClass === "VividAIReferenceVideo") {
    fields.unshift(...[["images", "图", 9], ["videos", "视频", 3], ["audios", "音频", 3]]
      .flatMap(([kind, label, max]) => [
        [`max_${kind}`, `${label}上限`, "number", 0, max],
        [`min_${kind}`, `${label}至少`, "number", 0, max],
      ]));
  }
  const controls = new Map();
  for (const [key, label, type, min, max] of fields) {
    const row = element("label", null, "vividai-field");
    row.append(element("span", label));
    const input = element("input");
    input.type = ["list", "numbers"].includes(type) ? "text" : type;
    input.setAttribute("aria-label", label);
    if (type === "checkbox") input.checked = rule[key];
    else input.value = Array.isArray(rule[key]) ? rule[key].join(", ") : rule[key];
    if (min !== undefined) { input.min = min; input.max = max; input.step = "1"; }
    row.append(input); form.append(row); controls.set(key, { input, type });
  }
  form.append(button("保存此模型的能力配置", () => {
    const model = value(node, "model");
    if (!model) { setStatus(node, "请先选择模型", true); return; }
    const next = { ...rule, _source: "user" };
    for (const [key, { input, type }] of controls) {
      if (!input.checkValidity()) { input.reportValidity(); return; }
      next[key] = type === "checkbox" ? input.checked : type === "number" ? Number(input.value)
        : input.value.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
          .map((s) => type === "numbers" ? Number(s) : s);
    }
    for (const kind of ["images", "videos", "audios"]) {
      if (next[`min_${kind}`] > next[`max_${kind}`]) {
        setStatus(node, "素材下限不能大于上限", true); return;
      }
    }
    if (next.duration_min > next.duration_max || next.durations.some((x) => !Number.isInteger(x) || x < 1)) {
      setStatus(node, "请检查时长范围及可选值", true); return;
    }
    try {
      setValue(node, "model_rules", JSON.stringify({ ...rules(node), [model]: next }));
      syncRule(node); markPending(node);
    } catch (error) { setStatus(node, error.message, true); }
  }));
  return form;
}

function markPending(node) {
  setStatus(node, "参数已修改，重新生成后生效；默认继续输出选中素材");
}

async function refreshProfiles() {
  profiles = (await request("/profiles")).profiles;
  for (const node of app.graph?._nodes || []) {
    if (node.comfyClass === "VividAIConfig") {
      combo(widget(node, "config_ref"), profiles.map((p) => p.id),
        Object.fromEntries(profiles.map((p) => [p.id, p.name])));
    }
  }
}

function credentialDialog(node) {
  const dialog = element("dialog", null, "vividai-dialog");
  const form = element("form"); form.method = "dialog";
  form.append(element("h3", "保存本机 VividAI 配置"));
  const selected = profiles.find((p) => p.id === value(node, "config_ref"));
  const inputs = {};
  for (const [key, label, type, initial] of [
    ["name", "配置名称", "text", selected?.name || "VividAI"],
    ["base", "API 根地址", "url", selected?.base || "https://vividai.run"],
    ["secret", "API Key（仅保存在本机）", "password", ""],
  ]) {
    const row = element("label", label);
    const input = element("input"); input.type = type; input.value = initial;
    input.autocomplete = "off"; input.required = true; input.name = key;
    row.append(input); form.append(row); inputs[key] = input;
  }
  const replace = element("input"); replace.type = "checkbox";
  const replaceLabel = element("label", "更新当前配置（影响引用此配置的节点）");
  replaceLabel.prepend(replace); replace.disabled = !selected; form.append(replaceLabel);
  const message = element("p"); form.append(message);
  form.append(button("保存到本机", async () => {
    if (!form.reportValidity()) return;
    try {
      const result = await request("/profiles", { method: "POST", body: JSON.stringify({
        name: inputs.name.value, base: inputs.base.value, secret: inputs.secret.value,
        ...(replace.checked && selected ? { id: selected.id } : {}),
      }) });
      inputs.secret.value = "";
      setValue(node, "config_ref", result.id);
      await refreshProfiles(); dialog.close();
    } catch (error) { message.textContent = error.message; }
  }));
  form.append(button("关闭", () => dialog.close()));
  dialog.append(form);
  dialog.addEventListener("close", () => { inputs.secret.value = ""; dialog.remove(); });
  document.body.append(dialog); dialog.showModal();
}

async function refreshModels(node) {
  const ref = profileRef(node);
  if (!ref) throw new Error("请连接 VividAI 配置节点，并选择本机配置");
  const { models } = await request(`/models?config_ref=${encodeURIComponent(ref)}`);
  const kind = node.comfyClass === "VividAITextToImage" ? "image" : "video";
  const compatible = models.filter((model) => model.kind === kind);
  const configured = rules(node);
  for (const model of compatible) {
    if (!configured[model.id] || configured[model.id]._source === "provider") {
      configured[model.id] = providerRule(model);
    }
  }
  setValue(node, "model_rules", JSON.stringify(configured));
  if (!compatible.some((model) => model.id === value(node, "model"))) {
    setValue(node, "model", compatible[0]?.id || "");
  }
  combo(widget(node, "model"), compatible.map((model) => model.id));
  syncRule(node);
  setStatus(node, `已读取 ${compatible.length} 个${kind === "image" ? "图片" : "视频"}模型及其能力；可在高级选项中覆盖`);
}

async function refreshHistory(node) {
  const key = value(node, "node_key");
  if (!key || !node._vividai) return;
  const state = await request(`/nodes/${key}`);
  node._vividai.state = state;
  const container = node._vividai.history;
  container.replaceChildren();
  if (state.task) setStatus(node, `${state.task.state} · ${state.task.job_id || "尚无任务 ID"}${state.task.error ? " · " + state.task.error : ""}`, state.task.state !== "running");
  else if (state.selected) {
    const selected = state.history.find((item) => item.id === state.selected);
    const changed = selected && (["model", "prompt", "quality", "ratio", "duration"]
      .some((field) => selected.snapshot[field] !== value(node, field))
      || JSON.stringify(selected.snapshot.rule) !== JSON.stringify(currentRule(node)));
    if (changed) markPending(node);
    else setStatus(node, "正在复用选中素材；只有显式标记才创建新任务");
  } else setStatus(node, "首次运行将生成一份素材；之后默认复用选中素材");
  for (const item of state.history) {
    const card = element("div", null, "vividai-material");
    const source = api.apiURL(`/vividai/nodes/${key}/media/${item.id}`);
    const preview = element(item.kind === "image" ? "img" : "video");
    preview.src = source; preview.setAttribute("aria-label", "历史生成素材");
    if (item.kind === "video") { preview.controls = true; preview.preload = "metadata"; }
    card.append(preview);
    card.append(element("small", new Date(item.created * 1000).toLocaleString()));
    card.append(button(item.id === state.selected ? "当前输出" : "启用此素材", async () => {
      try {
        await request(`/nodes/${key}/activate`, { method: "POST", body: JSON.stringify({ material_id: item.id }) });
        await refreshHistory(node);
        setStatus(node, "已切换输出素材，当前参数保留；下次运行输出此素材");
      } catch (error) { setStatus(node, error.message, true); }
    }));
    const details = element("details"); details.append(element("summary", "生成时参数"));
    details.append(element("pre", JSON.stringify(item.snapshot, null, 2))); card.append(details);
    container.append(card);
  }
}

function resetIdentity(node) {
  setValue(node, "node_key", crypto.randomUUID());
  setValue(node, "generation_token", "");
  node._vividai?.history.replaceChildren();
  setStatus(node, "新节点：首次运行将生成一份素材");
}

function installPanel(node) {
  const root = element("div", null, "vividai-panel");
  for (const [name, label] of [["model", "模型"], ["quality", "清晰度"], ["ratio", "比例"]]) {
    bindSelect(node, name, root, label);
  }
  const status = element("p", "首次运行将生成；之后默认复用选中素材", "vividai-status");
  const actions = element("div", null, "vividai-actions");
  actions.append(button("刷新模型", async () => {
    try { await refreshModels(node); } catch (error) { setStatus(node, error.message, true); }
  }));
  actions.append(button("下次运行重新生成", () => {
    setValue(node, "generation_token", crypto.randomUUID());
    setStatus(node, "已标记：下次正常运行工作流时生成一份新素材");
  }));
  actions.append(button("刷新历史 / 状态", async () => {
    try { await refreshHistory(node); } catch (error) { setStatus(node, error.message, true); }
  }));
  const advanced = element("div", null, "vividai-advanced");
  const ruleEditor = element("div", null, "vividai-advanced-content");
  ruleEditor.hidden = true;
  const advancedToggle = button("显示高级选项", () => {
    ruleEditor.hidden = !ruleEditor.hidden;
    advancedToggle.textContent = ruleEditor.hidden ? "显示高级选项" : "隐藏高级选项";
    advancedToggle.setAttribute("aria-expanded", String(!ruleEditor.hidden));
  });
  advancedToggle.className = "vividai-advanced-toggle";
  advancedToggle.setAttribute("aria-expanded", "false");
  advanced.append(advancedToggle, ruleEditor);
  const history = element("div", null, "vividai-history");
  root.append(status, actions, advanced, history);
  node._vividai = { root, status, ruleEditor, history };
  const dom = node.addDOMWidget("vividai_panel", "vividai_panel", root, { serialize: false });
  dom.serialize = false;
  dom.computeSize = () => [360, 300];
  node.setSize([Math.max(node.size[0], 400), Math.max(node.size[1], 640)]);
  for (const name of ["node_key", "generation_token", "model_rules"]) hide(widget(node, name));
  for (const name of ["model", "quality", "ratio", "prompt", "duration", "model_rules"]) {
    const w = widget(node, name);
    if (!w) continue;
    const original = w.callback;
    w.callback = function (...args) {
      const result = original?.apply(this, args);
      if (name === "model") syncRule(node);
      markPending(node); return result;
    };
  }
  if (!value(node, "node_key")) resetIdentity(node);
  syncRule(node);
}

app.registerExtension({
  name: "VividAI.PersistentGeneration",
  async setup() {
    const css = document.createElement("link"); css.rel = "stylesheet";
    css.href = new URL("./vividai.css", import.meta.url).href; document.head.append(css);
    try { await refreshProfiles(); } catch { /* UI will display details on interaction. */ }
    api.addEventListener("executed", (event) => {
      const node = app.graph?.getNodeById(event.detail.node);
      if (GENERATORS.has(node?.comfyClass)) refreshHistory(node).catch((e) => setStatus(node, e.message, true));
    });
    api.addEventListener("execution_error", () => {
      for (const node of app.graph?._nodes || []) {
        if (GENERATORS.has(node.comfyClass)) refreshHistory(node).catch(() => {});
      }
    });
  },
  beforeConfigureGraph() { loadingWorkflow = true; },
  afterConfigureGraph() {
    loadingWorkflow = false;
    const identities = new Set();
    for (const node of app.graph?._nodes || []) {
      if (!GENERATORS.has(node.comfyClass)) continue;
      if (!value(node, "node_key") || identities.has(value(node, "node_key"))) resetIdentity(node);
      identities.add(value(node, "node_key"));
      syncRule(node);
      refreshHistory(node).catch((e) => setStatus(node, e.message, true));
    }
    refreshProfiles().catch(() => {});
  },
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!ALL.has(nodeData.name)) return;
    const original = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function (...args) {
      const result = original?.apply(this, args);
      if (GENERATORS.has(this.comfyClass)) {
        if (!loadingWorkflow) resetIdentity(this);
        syncRule(this);
      }
      return result;
    };
    const connections = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function (...args) {
      const result = connections?.apply(this, args);
      if (GENERATORS.has(this.comfyClass) && !loadingWorkflow) markPending(this);
      return result;
    };
  },
  nodeCreated(node) {
    if (!ALL.has(node.comfyClass)) return;
    if (node.comfyClass === "VividAIConfig") {
      const root = element("div", null, "vividai-panel");
      bindSelect(node, "config_ref", root, "本机配置");
      const dom = node.addDOMWidget("vividai_config_select", "vividai_config_select", root, { serialize: false });
      dom.serialize = false; dom.computeSize = () => [280, 50];
      node.addWidget("button", "管理本机 API 配置", null, () => credentialDialog(node), { serialize: false });
      node.addWidget("button", "刷新本机配置列表", null, () => refreshProfiles().catch((e) => alert(e.message)), { serialize: false });
      combo(widget(node, "config_ref"), profiles.map((p) => p.id),
        Object.fromEntries(profiles.map((p) => [p.id, p.name])));
    } else {
      installPanel(node);
    }
  },
});
