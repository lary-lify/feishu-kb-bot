# 飞书内部客服助手（私有知识库 RAG + @机器人）

基于企业**私有知识库**（产品手册 Word/PDF、售后政策、FAQ 网页）构建的内部客服助手：
员工在**飞书中 @机器人** 提问，机器人基于私有知识库生成**准确、可溯源**的回复，并**标注引用来源**，
支持**多知识库 + 部门 RBAC 权限隔离**。

## 特性

- **多格式采集**：Word / PDF / TXT / Markdown / 网页（自动抓取正文）
- **混合检索**：向量（pgvector 余弦）+ 关键词（BM25，中文 jieba 分词）+ RRF 融合
- **可溯源生成**：DeepSeek 严格基于检索片段作答，禁编造，回复附带引用来源（文档名 + 段落 + 链接）
- **飞书长连接**：`lark-oapi` WebSocket 模式，无需公网 IP/服务器
- **多库 + RBAC**：shared/private 知识库，3 角色（super_admin / dept_admin / user），按 KB 授权
- **管理后台**：内置单页 Web UI（登录、建库、上传文档/URL、问答联调、用量审计）
- **轻量部署**：单个 `docker-compose`（PostgreSQL + pgvector + 应用）即可运行

## 技术栈

| 层 | 技术 |
|---|---|
| Web | FastAPI + Uvicorn |
| 数据库 | PostgreSQL 16 + pgvector（元数据 + 向量 + 检索合一） |
| 嵌入 | 通义 `text-embedding-v3`（DashScope） |
| 生成 | DeepSeek `deepseek-chat`（OpenAI 兼容，流式） |
| 检索 | pgvector 向量 + jieba/rank_bm25 关键词 + RRF |
| 飞书 | `lark-oapi` 长连接 + 互动卡片 |

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
cp .env.template .env          # 填入飞书/DeepSeek/DashScope 密钥
docker compose up -d --build
# 访问管理后台： http://<服务器IP>:8000
```

### 方式二：本地虚拟环境

```bash
python -m venv .venv && source .venv/Scripts/activate    # Windows
pip install -r requirements.txt
cp .env.template .env
# 准备一个 PostgreSQL + pgvector（或用 docker 单独起 db）
python -m app.db.init_db        # 初始化表、向量索引、默认管理员
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

默认管理员：`admin / Admin@123456`（请上线后立即修改 `.env` 中 `DEFAULT_ADMIN_PASSWORD`）。

> **安全自检（v1.0.1+）**：启动时会校验 `JWT_SECRET`，若为默认/占位符/少于 16 位将**拒绝启动**，并提示配置强密钥。仅本地开发可设 `ALLOW_DEFAULT_SECRET=1` 临时绕过（生产环境禁用）。
>
> **CORS**：管理 UI 与 API 同域部署时无需配置；如需跨域前端，在 `.env` 设置 `CORS_ORIGINS=https://a.com,https://b.com`（留空 = 仅同源）。

### 离线联调（无需密钥）

设置以下环境变量可跳过真实模型调用，便于先打通链路：

```bash
export EMBEDDING_MOCK=1
export LLM_MOCK=1
export ALLOW_DEFAULT_SECRET=1   # 本地开发跳过 JWT 强密钥自检
```

此时嵌入返回确定性随机向量、生成返回占位文本，完整管线（采集→检索→卡片）仍可验证。

## 飞书开放平台配置

1. 打开 [飞书开放平台](https://open.feishu.cn/) → 创建企业自建应用。
2. **凭证与基础信息** 获取 `App ID` 与 `App Secret`，填入 `.env` 的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`。
3. **添加应用能力** → 开通「机器人」。
4. **事件订阅** → 开启**长连接**（无需配置公网回调地址）；添加事件 `接收消息 v2.0`（`im.message.receive_v1`）。
5. 将机器人加入目标群，或在单聊中直接对话。
6. 群聊中 **@机器人** 提问；单聊直接提问。支持 `/kb <知识库名> 问题` 限定范围。

> 长连接模式要求机器人进程持续运行（Docker 中以守护线程常驻），无需公网可达。

## 使用流程

1. 管理后台登录 → 新建知识库（可 shared 全员可读，或 private 按授权）。
2. 选择知识库 → 上传产品手册/售后政策，或添加 FAQ 网页 URL（自动抓取、分块、向量化、入索引）。
3. 在「问答联调」中验证检索与回答效果。
4. 飞书中 @机器人 提问，收到含「回答 + 参考来源」的卡片。

## 目录结构

```
app/
  config.py              配置（pydantic-settings 读 .env）
  db/                    引擎、模型、初始化（建表+向量索引+种子）
  security/              JWT 与 RBAC
  clients/               embedding（通义）、llm（DeepSeek）、feishu（发卡片）
  services/
    parser/              多格式文档解析
    chunking.py          分块策略
    ingestion.py         采集编排
    bm25.py              应用内 BM25 索引
    retrieval.py         混合检索 + RRF
    rag.py               grounding 提示 + 生成 + 引用
    audit.py             审计/用量
  api/                   auth/kbs/users/documents/chat/audit
  feishu_bot/            bot.py（长连接收消息）、card.py（引用卡片）
  static/index.html      管理后台单页
```

## 引用来源说明

每条引用包含：文档名称、所属知识库、段落序号、相似度分数；若入库时携带 `source_url`（网页链接或共享盘链接），
则在飞书卡片中渲染为可点击「查看」链接，否则展示为「📄 文档名 · 第N段」纯文本，满足可溯源要求。

## 注意事项

- 中文 BM25 采用应用内 `jieba` 分词，避免依赖 PostgreSQL 中文分词扩展，保持单容器部署。
- 向量检索硬门限（`RAG_SCORE_THRESHOLD`，默认 0.30）：相似度低于阈值的片段不进入候选，减少误引。
- 飞书卡片不适配逐字流式，机器人采用「生成完整答案后发一张含全部来源的卡片」；Web 端保留 SSE 流式。
- 所有密钥经 `.env` 注入，模板已脱敏，请勿将真实密钥提交入库。
