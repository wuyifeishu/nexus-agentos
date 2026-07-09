---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 3e9b297b16411e0e0848fc0302358070_55a508ef74ac11f1897e5254002afed2
    ReservedCode1: oTREFbv0MEDMfFDNJIgt1bxa9SlVIgcWsOEOcgnGQ+RlQQJ30m5jwRXWGF4b5pnglFt2+vha4yl6fAtuni/tTxCCLfKoOOmbwSdMkL2BT1wqgvImPvQXU7R1SuFt90OLUGOH1vAMm1SeJl34t+oTh8V342TWz1eaogZ4TCtPRe0R+oke2DWas6tL37M=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 3e9b297b16411e0e0848fc0302358070_55a508ef74ac11f1897e5254002afed2
    ReservedCode2: oTREFbv0MEDMfFDNJIgt1bxa9SlVIgcWsOEOcgnGQ+RlQQJ30m5jwRXWGF4b5pnglFt2+vha4yl6fAtuni/tTxCCLfKoOOmbwSdMkL2BT1wqgvImPvQXU7R1SuFt90OLUGOH1vAMm1SeJl34t+oTh8V342TWz1eaogZ4TCtPRe0R+oke2DWas6tL37M=
---

# NexusAgentOS vs 主流框架 — 差距分析 2026Q3

> 基于 2026-07-01 市场调研数据，对标 OpenClaw、Hermes、Claude Code、Cursor、OpenCode 等主流产品。

---

## 一、市场格局速览（2026年中）

### 1.1 框架三梯队

| 梯队 | 代表产品 | 规模 | 核心壁垒 |
|------|---------|------|---------|
| **T0 — 巨无霸** | OpenClaw (345K stars) | 13,700+ Skills, 50+ 渠道 | 生态 == 护城河 |
| **T1 — 新锐王者** | Hermes (145K stars), Claude Code | 自我进化+桌面端 | 持久记忆+闭环学习 |
| **T1 — IDE 内置** | Cursor, Copilot, Codex (500万周活) | 编辑器深度集成 | 用户基数碾压 |
| **T2 — 开源 CLI** | OpenCode (75+ 模型), Gemini CLI | 模型无关, BYO Key | 零成本+可自托管 |

### 1.2 竞争已从"模型竞赛"转向"生态竞赛"

2026 年 LLM 能力趋同，差异化全部落在 **Skill 生态 / 桌面体验 / 多 Agent 编排 / 持久记忆** 四个维度。

---

## 二、NexusAgentOS 差距矩阵

| 维度 | NexusAgentOS (1.7.5) | OpenClaw | Hermes | Claude Code | Cursor | 差距评级 |
|------|---------------------|----------|--------|-------------|--------|---------|
| **Skills 数量** | 0 (空壳) | 13,700+ | 118 (自生成) | 20+ | 内置 | 🔴 致命 |
| **Skill 市场** | 导入器就绪 | ClawHub 5,700+ | 自学习闭环 | Anthropic 官方 | 无 | 🔴 致命 |
| **桌面端** | Textual TUI (终端) | TUI + 多平台 | Hermes Desktop (GUI) | CLI + IDE | Electron IDE | 🟡 刚起步 |
| **渠道** | 10 (5国际+5国内占位) | 50+ | Telegram 等 | 无 (CLI) | IDE内 | 🟡 中等差距 |
| **持久记忆** | PTC SessionManager | 有限 | FTS5+Honcho+LLM摘要 | 无 | 项目级 | 🟡 中等差距 |
| **自学习** | 无 | 无 | ✅ 闭环学习 | 无 | 无 | 🔴 缺失 |
| **多Agent编排** | ParallelExecutor (DAG) | Sub-graph | 基础 | 无 | Cloud Agents | 🟢 对齐 |
| **社区** | 0 | 345K stars | 145K stars | 闭源 | 闭源 | 🔴 缺失 |
| **MCP支持** | 导入器中 | 原生 | 原生 | 原生 | 原生 | 🟡 需补 |
| **沙箱安全** | 本地运行 | CVE 8.8, 341不良技能 | 5种沙箱后端 | 云端 | 云端 | 🟢 优于OpenClaw |

---

## 三、Skill 生态差距 — 核心瓶颈

### 3.1 市场规模对比

```
NexusAgentOS:  0 skills ━━━━━━━━━━━━━━━━━━━━━━ 空壳
Hermes:       118 skills  ██░░░░░░░░░░░░░░░░░░  自生成闭环
Claude Code:   20 skills  ░░░░░░░░░░░░░░░░░░░░  官方精选
OpenClaw:  13,700 skills  ████████████████████  + ClawHub 5,700+
SkillsMP:  164万文件索引  ████████████████████████████  全网聚合
```

### 3.2 我们的现状

- **导入器已通**：`marketplace/importer.py` 支持 OpenClaw/GitHub/HuggingFace 三源导入
- **市场壳已就位**：`desktop/skill_store_server.py` + 内置 7 大外部市场链接
- **但没有自有技能**：导入的是别人的技能，格式兼容性无保证

### 3.3 桌面壳内置 Web 市场方案（已实现）

```
┌─────────────────────────────────────────────┐
│  NexusAgentOS Desktop                        │
│  ┌────────────┬─────────────────────────────┐│
│  │ Sidebar    │  Skill Store WebView         ││
│  │            │                              ││
│  │ OpenClaw ✓ │  ┌───────────────────────┐  ││
│  │ ClawHub    │  │ skills.mp (iframe)    │  ││
│  │ SkillsMP   │  │                       │  ││
│  │ LobeHub    │  │  搜索 → 安装          │  ││
│  │ SkillHub   │  │                       │  ││
│  │ skills.sh  │  └───────────────────────┘  ││
│  │ awesome-.. │                              ││
│  └────────────┴─────────────────────────────┘│
│  Status: 3 skills installed                  │
└─────────────────────────────────────────────┘
```

**工作流**：点击侧栏 → 加载对应市场页面（iframe 嵌入 GitHub 页面或官网）→ 搜索 → 点击安装按钮 → 调用 `OpenClawImporter.import_skill()` 本地落盘。

---

## 四、优先补肉路线（P0-P3 重新定级）

### P0 — 立即冲（本周）

| 事项 | 工作量 | 当前状态 |
|------|--------|---------|
| **桌面 Web 技能市场** | ✅ 已完成 | `skill_store_server.py` + `static/index.html` |
| **TUI 集成 MarketPanel** | 1 模块 | 待做：TUI 增加 Market 标签页 |
| **OpenClaw 种子技能全量导入** | 1 脚本 | 导入器就绪，跑一次批量导入 |

### P1 — 本周完成

| 事项 | 工作量 | 说明 |
|------|--------|------|
| **MCP 协议原生支持** | 1-2 模块 | 对标 Hermes/OpenClaw 的 MCP Tool |
| **自建 10 个种子技能** | 2 天 | 从 OpenClaw 精选 + 汉化 + 优化 |
| **GitHub 仓库初始化 + README** | 半天 | Star 从 0 开始 |

### P2 — 两周内

| 事项 | 工作量 | 说明 |
|------|--------|------|
| **渠道 10→20** | 1周 | Discord Threads, Slack Blocks 等 |
| **LSP 诊断集成** | 3-5天 | 对标 Cursor 的实时代码检查 |
| **HuggingFace 社区导入** | 1天 | 利用已有 HFImporter |

### P3 — 一个月

| 事项 | 工作量 |
|------|--------|
| **自学习闭环** (对标 Hermes) | 大工程 |
| **桌面 GUI** (替代 TUI, pywebview/Electron) | 大工程 |
| **Skill 社区运营** | 持续 |

---

## 五、核心结论

1. **Skill 生态是唯一致命差距**。OpenClaw 的 13,700 个技能是 345K stars 的根基，Hermes 的自我进化闭环是 145K stars 的未来。我们没有技能就没有用户。

2. **桌面壳内置 Web 市场是正确方向**。Hermes Desktop 证明了"桌面入口+技能商店"的组合拳有效。我们的 TUI + Web 市场方案比纯 CLI 好，但距离 Electron 级桌面仍有差距。

3. **当前最该做的事**：导入 OpenClaw 14 个种子技能跑通闭环 → 自建 10 个差异化技能 → TUI 加 MarketPanel → 发布 GitHub → 写 Blog → 从 0 开始攒 Star。

4. **不需要追赶 13,700 个技能**。Hermes 只用 118 个自生成技能就冲到 145K stars，说明质量 > 数量。我们的优势是架构干净、安全沙箱优于 OpenClaw（后者有 341 个不良技能 CVE），可以从"安全精选"的定位切入。

---

*分析时间：2026-07-01 · NexusAgentOS v1.7.5*
*（内容由AI生成，仅供参考）*
