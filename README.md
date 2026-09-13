# zipplin_skills

可复用的 AI Agent 技能集合。

## 技能

| 技能 | 用途 |
|---|---|
| [itinerary-visualizer](itinerary-visualizer/SKILL.md) | 把文字行程转换为含真实地理底图、纸感地图、每日路线和单行实景图集的离线 HTML 网页。 |

## 使用与验证

把技能目录复制到所用 Agent 的技能目录，然后按 `SKILL.md` 工作流使用。

```bash
python3 itinerary-visualizer/scripts/test_skill.py
python3 itinerary-visualizer/scripts/build_itinerary.py \
  --input /absolute/path/itinerary.json \
  --output /absolute/path/output-dir \
  --require-complete
```

正式生成需要已核实的路线、带来源的本地实景照片，以及底图或通过环境变量提供的 `AMAP_WEB_KEY`（也支持 `AMAP_KEY`）。Key 不应写入仓库。内置示例只用于离线版式与逻辑测试。

浏览器回归需要 Playwright 及 Chromium：

```bash
node itinerary-visualizer/scripts/test_browser.cjs /absolute/path/output-dir/index.html
```

若 Playwright 不在默认模块查找路径，可用 `PLAYWRIGHT_MODULE` 指定模块路径。
