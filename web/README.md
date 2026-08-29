# LLM-Wiki OS — Web 前端

> 赛博风多模 SPA：认证 + 探求模式 + 织网模式 + 报告模式 + 管理面板

---

## 技术栈

| 层 | 选型 |
|---|---|
| 框架 | React 18 (Functional Components + Hooks) |
| 构建 | Vite 6 |
| 样式 | Tailwind CSS 3 (Dark Mode, 毛玻璃 + 发光) |
| 图形 | react-force-graph-2d (力导向物理图) |
| Markdown | react-markdown + remark-gfm + remark-math + rehype-katex |
| 认证 | JWT Token (sessionStorage) |
| 流式通信 | SSE (EventSource / fetch + ReadableStream) |

---

## 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器（自动代理 API 到 8888）
npm run dev
# → http://localhost:5173

# 构建生产包（由 app.py 静态服务）
npm run build
# → web/dist/
```

---

## 多模布局

```
┌──────────────┬────────────────────────────────────────────────┐
│              │                                                │
│  Sidebar     │          主画布                                 │
│  260px       │                                                │
│              │  ┌───────────┐ ┌────────────┐ ┌──────────────┐ │
│  🧠 Logo     │  │ 探求模式:  │ │ 织网模式:   │ │ 报告模式:    │ │
│  探求/织网/   │  │ 对话气泡   │ │ 70%力导向图 │ │ 主题输入     │ │
│  报告切换    │  │ 终端轨迹   │ │ 30%控制台   │ │ 结构化输出   │ │
│  沙箱选择    │  │ Markdown   │ │ 熔炉/审批/  │ │ KaTeX 数学   │ │
│  状态指示    │  │ KaTeX数学  │ │ 雷达/档案   │ │              │ │
│  管理入口    │  │ 输入框     │ │             │ │              │ │
│              │  └───────────┘ └────────────┘ └──────────────┘ │
│              │                                                │
└──────────────┴────────────────────────────────────────────────┘
```

---

## 页面与组件

### 认证与设置

| 组件 | 说明 |
|------|------|
| `Login.jsx` | 登录/注册页，JWT Token 存储到 sessionStorage |
| `Settings.jsx` | BYOK 设置：选择 LLM 供应商 + 填入 API Key |
| `AuthContext.jsx` | React Context：全局认证状态、登录/登出/Token 管理 |

### 主模式

| 组件 | 说明 |
|------|------|
| `QueryMode.jsx` | **探求模式**：SSE 流式对话、终端日志、Markdown + KaTeX 渲染、会话历史加载 |
| `ForgeMode.jsx` | **织网模式**：70% 力导向图 + 30% 控制台（CyberForge / Inbox / Radar / AuditLog 四 Tab） |
| `ReportMode.jsx` | **报告模式**：指定主题 → 批量材料检索 → 分章节结构化报告 |

### 子组件

| 组件 | 说明 |
|------|------|
| `ForceGraph.jsx` | 力导向图：节点点击 → 双链跳转 → `/api/concept` 读取 Markdown 弹窗 |
| `Sidebar.jsx` | 左侧栏：模式切换、沙箱选择、管理员入口 |
| `SessionHistory.jsx` | 会话历史列表（从 `/api/sessions` 加载） |
| `AdminDashboard.jsx` | **管理面板**（三 Tab）：用户&会话管理、任务日志、系统控制台 SSE |
| `CyberForge.jsx` | 文件拖拽摄入 + lint/autofill 触发按钮 |
| `Inbox.jsx` | 隔离审批区：待确认草稿列表，支持预览/入库/废弃 |
| `Radar.jsx` | 需求雷达：搜索落空记录，阈值预警 |
| `AuditLog.jsx` | 操作审计日志 |

---

## 目录结构

```
web/
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
└── src/
    ├── main.jsx              # React 入口
    ├── App.jsx               # 路由 + 模式切换 + 管理面板入口
    ├── index.css             # Tailwind + 自定义动画 + KaTeX 样式
    ├── contexts/
    │   └── AuthContext.jsx   # JWT 认证 Context（sessionStorage）
    ├── data/
    │   └── mockData.js       # Mock 数据（开发用）
    └── components/
        ├── Login.jsx         # 登录/注册
        ├── Settings.jsx      # BYOK 模型设置
        ├── Sidebar.jsx       # 左侧栏
        ├── QueryMode.jsx     # 探求模式（SSE + Markdown + KaTeX）
        ├── ForgeMode.jsx     # 织网模式容器
        ├── ReportMode.jsx    # 报告模式
        ├── ForceGraph.jsx    # 力导向图 + 概念阅读窗
        ├── SessionHistory.jsx # 会话历史
        ├── AdminDashboard.jsx # 管理面板（3 Tab）
        ├── CyberForge.jsx    # 赛博熔炉
        ├── Inbox.jsx         # 隔离审批
        ├── Radar.jsx         # 需求雷达
        └── AuditLog.jsx      # 审计日志
```

---

## 关键技术决策

| 决策 | 原因 |
|------|------|
| react-markdown + KaTeX 替代 marked | 解决 XSS 风险（`dangerouslySetInnerHTML`）+ 支持数学公式渲染 |
| sessionStorage 替代 localStorage | 关闭标签页即需重新登录，避免多账号互相踢出 |
| SSE (fetch + ReadableStream) 替代 WebSocket | 单向推送足够，无需双向通信，更简单 |
| 生产构建由 app.py 静态服务 | `StaticFiles` + SPA 回退路由，无需 Nginx |

---

## 对接后端

前端通过 `apiFetch()` 封装函数自动附加 JWT Token 到 `Authorization` header：

```javascript
// AuthContext.jsx 提供
const apiFetch = (url, options) => fetch(url, {
  ...options,
  headers: { ...options?.headers, Authorization: `Bearer ${token}` }
})
```

SSE 端点（EventSource 不支持自定义 header）通过 URL query parameter 传递 Token：

```javascript
const es = new EventSource(`/api/admin/logs?token=${token}`)
```

---

## 授权声明

**无开源许可证。** 仅供项目内部使用，未经授权禁止复制、分发或商用。
