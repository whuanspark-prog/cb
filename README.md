# 📎 Clip Bill - 自主财务记账 Agent

> **基于多模态大模型 (VLM) 与自适应 Agent 架构的“无感化”个人财务管家。**

Clip Bill 旨在打破微信与支付宝的账单孤岛，通过“截图即记账”的极简体验，利用 VLM 视觉识别与智能决策引擎，打造越用越懂你的私人 AI 财务助手。

---

## ✨ 核心亮点

### 1. 视觉感知（Perception）

* **多模态提取**：调用 `Qwen-VL-Max` 进行视觉拟合，精准识别非标准化截图（如跨图截断、反光、同图连拍）。
* **反幻觉机制**：强制边界判定，对信息缺失的流水严禁“脑补”，确保账本绝对真实。

### 2. 三级漏斗分类引擎（Decision Engine）

系统通过三层过滤，在确保**分类准确率**的同时极大降低 **API 推理成本**：

1. **Level 1：个人记忆拦截 (One-Shot Learning)** 读取 `user_rules.json`，实现“一教即会”。用户手动纠偏一次，系统永生记住该商户分类。
2. **Level 2：全局专家规则** 内置行业基准字典（如：滴滴 -> 交通），实现 O(1) 秒级拦截。
3. **Level 3：LLM 语义兜底** 仅对长尾未知商户调用大模型进行上下文推理，若置信度低则标记为【待人工确认】。

### 3. 双面板联动架构 (CUI + GUI)

* **左侧 CUI**：对话式录入与自然语言纠偏。
* **右侧 GUI**：可视化仪表盘，支持扇形图联动下钻与 HITL (人机回环) 工作台。

---

## 🚀 快速启动

### 1. 克隆/下载本项目并安装依赖

```bash
pip install -r requirements.txt

```

### 2. 配置 API Key (DashScope)

本项目核心提取能力基于阿里云通义千问多模态模型。

```powershell
# Windows PowerShell
$env:DASHSCOPE_API_KEY="你的 API Key"

# Linux/Mac
export DASHSCOPE_API_KEY="你的 API Key"

```

### 3. 启动 Web Agent

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000

```

访问：`http://127.0.0.1:8000`

---

## 📂 项目结构

```text
├── server.py              # FastAPI 后端核心逻辑
├── clip_bill.db           # SQLite 数据库（存储流水与状态）
├── user_rules.json        # 个人规则记忆库 (One-shot Learning)
├── requirements.txt       # 项目依赖
├── web/                   # 前端静态资源
│   ├── index.html         # 双面板布局
│   ├── styles.css         # 马卡龙视觉样式
│   └── app.js             # 信号驱动与数据刷新逻辑
└── README.md

```

---

## 📈 性能预期 (Metrics)

| 指标维度 | 指标名称 | 定义/公式 | 目标预期 |
| --- | --- | --- | --- |
| **成本控制** | LLM 拦截率 | (L1命中 + L2命中) / 总流水 | **> 60%** |
| **模型表现** | AI 分类准确度 | 1 - (人工修改次数 / 总流水) | **> 90%** |
| **数据质量** | 脏数据废弃率 | 触发审计丢弃的流水 / 总流水 | 5%~15% |

---

## 🛣️ 演进路线

* [x] **V1.0**: 单机版 Agent Pipeline，完成核心闭环。
* [ ] **V1.5**: 引入时间衰减权重优化规则库，上线 SAA​​S 架构。
* [ ] **V2.0**: 接入微信生态，实现家庭共享账本。

---

**作者**: Mia Wu

**版本**: V1.0

*如果这个项目对你有帮助，欢迎点一个 ⭐ Star！*
