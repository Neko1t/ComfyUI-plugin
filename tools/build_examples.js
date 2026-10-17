// Generate importable workflows using the actual ComfyUI frontend serializer.
(async () => {
  const { app } = await import("/scripts/app.js");
  const result = {};
  for (const [file, type] of [["text-to-image", "VividAITextToImage"],
    ["text-to-video", "VividAITextToVideo"], ["reference-video", "VividAIReferenceVideo"]]) {
    await app.loadGraphData({ nodes: [], links: [], groups: [], config: {}, extra: {}, version: 0.4 });
    const config = LiteGraph.createNode("VividAIConfig");
    const generate = LiteGraph.createNode(type);
    const save = LiteGraph.createNode(type === "VividAITextToImage" ? "SaveImage" : "SaveVideo");
    config.pos = [20, 100]; generate.pos = [360, 100]; save.pos = [860, 100];
    for (const node of [config, generate, save]) app.graph.add(node);
    config.connect(0, generate, 0); generate.connect(0, save, 0);
    generate.widgets.find((w) => w.name === "prompt").value = "A quiet forest at sunrise, soft light";
    if (type === "VividAIReferenceVideo") {
      const image = LiteGraph.createNode("EmptyImage"); image.pos = [20, 400];
      app.graph.add(image);
      image.connect(0, generate, generate.inputs.findIndex((input) => input.name === "image_1"));
    }
    const workflow = app.graph.serialize();
    workflow.extra.ds = { scale: 0.75, offset: [30, 70] };
    result[file] = workflow;
  }
  return result;
})();
