---
name: bilibili-viral
description: 每天抓取 B站 AI工具/副业/个人IP 赛道的爆款视频，默认直接复刻已验证爆款的选题、标题结构、钩子、段落和镜头，重写口播并生成每周 5 条可拍内容（脚本 + 2 版封面 + 本地仪表盘）。当用户说“跑一下 B站爆款雷达”“今天拍什么”“复刻本周爆款/生成脚本封面”时使用。
---

# B站爆款内容雷达

这个技能把 B站公开数据变成一套可执行的周更内容系统：**抓取 → 拆解 → 复刻 → 脚本 → 封面 → 仪表盘**。默认不要求用户自己想创意：先从近 7 天爆款里选 5 条最可复刻的，保留原片的选题、标题承诺、开头钩子、内容段落和镜头顺序，重写全部表达，换成自己的素材与案例。

## 何时使用

- 用户要“看看最近 B站什么火”“找 AI 工具/副业赛道的选题”
- 用户要“本周拍什么”“生成 5 条脚本/封面”
- 定时任务每天 09:00 自动采集，周一生成周计划
- 用户要复盘某条爆款的标题、钩子、结构、封面

## 项目位置

优先在 `BILI_VIRAL_HOME` 指向的目录运行；未设置时用当前目录。当前目录没有 `bili_viral/` 时，先把仓库克隆到 `~/.bili-viral` 并运行 `bash scripts/bootstrap.sh`。

```bash
export BILI_VIRAL_HOME="${BILI_VIRAL_HOME:-$HOME/.bili-viral}"
cd "$BILI_VIRAL_HOME"
```

配置：`config.yaml`；数据：`data/`；产出：`output/`。首次安装先运行 `bash scripts/bootstrap.sh`，之后用 `.venv/bin/python -m bili_viral ...` 或激活 `.venv`。

## 核心命令

```bash
# 1. 环境检查（首次/异常时）
python3 -m bili_viral doctor

# 2. 采集：首次回填 7 天，日常 2 天
python3 -m bili_viral collect --days 7 --open
python3 -m bili_viral collect --days 2

# 3. 生成 agent 分析任务包（collect 会自动做）
python3 -m bili_viral analyze-pack --top 20

# 4. 校验 JSON 结构
python3 -m bili_viral validate

# 5. 检查脚本原创性/结构/合规
python3 -m bili_viral scriptcheck --week 2026-W47

# 6. 生成封面（每条 2 版）
python3 -m bili_viral cover --week 2026-W47

# 7. 重渲染仪表盘
python3 -m bili_viral render --open

# 8. 状态/清理
python3 -m bili_viral status
python3 -m bili_viral prune --days 90
```

## 每日流程（自动任务，约 3-5 分钟）

1. 确认 Chrome 已登录 bilibili.com（字幕需要登录态）。
2. 运行 `python3 -m bili_viral collect --days 2`。
3. 读取 `data/analysis/<今天>/prompt.md`、`top.json`、`transcripts.md`、`contact-sheet.jpg`。
4. 如果今天不是周一：只更新 `data/analysis/<今天>.json`（单条拆解），不生成新周计划。
5. 如果是周一（或还没有本周计划）：按下面的“周一流程”生成 5 条。
6. 运行 `validate`、`render`，把仪表盘路径告诉用户。

## 周一流程（复刻 5 条，默认模式）

1. 读 `data/analysis/<今天>/top.json`，按爆款分/播放/涨速取前 20 条。
2. 给每条打“可复刻性”：是否录屏/口播可拍、工具是否可获得、字幕是否完整、是否有版权/真人肖像风险、是否能用自己的素材替换案例。优先选 5 条高可复刻的，不要求覆盖两个方向，但尽量让选题不重复。
3. 读原片字幕和封面接触表，按“钩子 → 承诺 → 演示/步骤 → 证据 → 行动号召”拆成时间轴；没有字幕的条目只能从标题/封面/描述判断，必须标注“字幕缺失”，不得编造口播。
4. 写 `data/analysis/<今天>.json`：`remake_angle` 改写成“复刻说明”，明确保留原片哪几段、替换哪些案例/素材/表达。
5. 写 `data/plans/<week>.json`：顶层 `mode: "clone"`；每条 idea 必须有 `clone_of`（原片 BV）、`source_title`、`fidelity`（如“结构 1:1，案例与表达重写”）、`refs`（至少含原片 + 1 条补充参考）。
6. 写 5 份脚本到 `output/scripts/<week>-<id>-<slug>.md`：保留原片的段落顺序、信息密度、钩子类型和镜头节奏；逐句重写，换成自己的案例、截图、口头禅；标题候选贴近原片承诺，但加“复刻版/实测/保姆级”等区分，避免冒充原片。
7. 写 `data/cover_specs/<week>.json`：复刻原片封面的公式（构图/大字位置/配色/对比），不直接用原图；每条 1 个 spec，5 种风格轮换。
8. 运行：
   ```bash
   python3 -m bili_viral validate
   python3 -m bili_viral scriptcheck --week <week>
   python3 -m bili_viral cover --week <week>
   python3 -m bili_viral render
   ```
9. 如果有脚本失败：重写重合段落或换叙事顺序，不要降低阈值；如果某条原片不可复刻（工具下架/素材拿不到/版权风险），从 top 20 换下一条，不要编造 BV 或数据。
10. 视觉检查 `output/dashboard/index.html`、`output/weekly/<week>.md`、5 张 v1 封面；确认脚本页标注原片 BV，且没有逐字复制。
11. 向用户汇报：本周 5 条标题、每条复刻自哪个 BV、1 句拍摄方式、封面路径、仪表盘/周报路径。

## 输出结构（必须遵守）

`data/analysis/<YYYY-MM-DD>.json`：

```json
{
  "date": "YYYY-MM-DD",
  "videos": [
    {
      "bvid": "BV...",
      "topic": "一句话选题，不是标题复述",
      "why_viral": ["爆点1", "爆点2", "爆点3"],
      "hook": "前 3 秒逐字拆解",
      "structure": ["0:00 钩子", "0:15 冲突", "..."],
      "remake_angle": "复刻说明：保留原片哪几段，替换哪些案例/素材/表达",
      "audience": "谁会被打动，为什么",
      "cover": {
        "style": "黑黄大字/左右对比/截图标注/渐变科技/人像大字",
        "text": "封面大字",
        "color": "主色 hex + 辅助色",
        "why": "为什么能提高点击",
        "formula": "可复用公式"
      },
      "scores": {"topic": 8, "cover": 7, "script": 8, "production": 6},
      "risks": ["事实/版权/合规风险"]
    }
  ]
}
```

`data/plans/<week>.json`：

```json
{
  "week": "2026-W47",
  "mode": "clone",
  "theme": "本周复刻 5 条已验证爆款",
  "summary": "按热度与可复刻性选 5 条；保留结构，重写表达",
  "ideas": [
    {
      "id": "w01",
      "day": "周一",
      "mode": "clone",
      "topic": "选题",
      "clone_of": "BV...",
      "source_title": "原片标题",
      "fidelity": "结构 1:1，表达与案例重写",
      "title_options": ["标题1", "标题2", "标题3"],
      "hook": "前 3 秒",
      "angle": "复刻说明：保留什么、换什么",
      "why_now": "为什么现在做",
      "outline": ["0:00 ...", "0:20 ...", "..."],
      "refs": ["BV...", "BV..."],
      "cover_title": "封面大字",
      "cover_subtitle": "副标题",
      "badge": "AI 工具",
      "difficulty": "低/中/高",
      "fact_checks": ["需要核实的事实"],
      "script_path": "output/scripts/<week>-w01-xxx.md"
    }
  ]
}
```

`data/cover_specs/<week>.json`：

```json
{
  "week": "2026-W47",
  "covers": [
    {
      "id": "w01",
      "idea_id": "w01",
      "style": "black_yellow",
      "title": "封面大字",
      "subtitle": "副标题",
      "badge": "AI 工具",
      "accent": "#FFD400",
      "ref_bvid": "BV..."
    }
  ]
}
```

## 内容约束（硬性）

- 赛道：AI 工具/效率实操 + 副业/搞钱/个人 IP。
- 创作者默认：不出镜，录屏 + 口播/字幕卡；每周 5 条；3-6 分钟。
- 脚本汉字 900-1800（检查器允许到 2200，但目标 900-1800）。
- 默认复刻模式：保留原片选题、标题承诺、钩子、段落顺序、镜头节奏；必须重写全部口播与字幕，换自己的案例/截图/素材，不复制原句。
- 每条脚本至少引用 2 个真实竞品 BV（含 `clone_of` 原片）；标题加“复刻版/实测”等区分，封面不直接用原图。
- 复刻不是搬运：不下载/不剪原片、不使用原片独有素材、不冒充原片作者；画面里标注“参考 BV”。
- 与任一竞品字幕 8-gram 重合必须 <15%。
- 不出现“稳赚/躺赚/保证收益/百分百/无风险/包赚/一夜暴富/月入十万/日入过万”等表述。
- 封面大字 8-14 字；避免“震惊/必看/全网首发”等空词；必须能在 1 秒内读懂利益点。
- 不下载/搬运完整视频；只抓公开元数据、AI 字幕、封面，用于分析。
- 发布前人工复核工具版本、价格、截图隐私、版权。

## 失败处理

| 现象 | 处理 |
|---|---|
| `412` / HTML / 登录失效 | 打开 Chrome 登录 bilibili.com；`collect --refresh-cookies`；仍失败则报告用户 |
| 字幕缺失 | 标记 `transcript_status=missing`，不跑 ASR，不编造口播 |
| 搜索 0 条 | 降低 `min_play` 或换关键词；检查 `pubtime` 窗口 |
| 封面下载失败 | 使用占位图；检查 `i0.hdslb.com` 是否可访问 |
| `validate` 失败 | 按错误逐项补字段，不要跳过 |
| `scriptcheck` 重合 | 重写重合段落，换叙事顺序/例子；不要只改同义词 |
| 原片不可复刻 | 工具下架/素材拿不到/版权风险时，从 top 20 换下一条；不要硬编或编造 BV |
| 磁盘不足 | 清理 `data/cache/`、旧 `output/covers/`；保留 DB 和脚本 |

## 参考

- `references/analysis-rubric.md`：爆款判断、评分、拆解维度
- `references/cover-playbook.md`：5 种封面风格、公式、文字/对比度规则
- `references/script-playbook.md`：6 种脚本结构、7 段模板、原创性检查

## 定时任务提示词

每天 09:00 由 `schedule_create` 投递：

> 运行 B站爆款雷达的每日流程：先 `cd "${BILI_VIRAL_HOME:-$HOME/.bili-viral}" && python3 -m bili_viral collect --days 2`；读取 `data/analysis/<今天>/prompt.md`；更新当日分析；如果今天是周一或还没有本周计划，按 `skills/bilibili-viral/SKILL.md` 的复刻模式选 5 条高可复刻爆款，保留其选题/标题结构/钩子/段落/镜头，重写口播并生成脚本/封面；运行 validate、scriptcheck、cover、render；最后汇报 5 条标题、各自复刻自哪个 BV、拍摄方式和仪表盘路径。不要下载/搬运视频、不要自动发布、不要编造 BV 或数据。
