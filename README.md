# home-flow

基于 RBAC 权限控制的二手房成交数据智能问答系统。

## 核心能力

- 扫描 `城市/日期` 目录下的成交贺报图片
- OCR/文本解析成交字段并写入 SQLite `orders` 表
- 不确定数据进入每日待办
- 登录、会话鉴权、角色权限管理
- 店员/店长/管理员按城市权限查询成交数据
- 智能问答查询数据库并返回统计、明细和图表数据
- 可选接入 DeepSeek 或通义千问等 OpenAI 兼容大模型
- 预留 RAG 知识库表，用于后续回答制度、流程、业务知识

## 后端启动

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/init_db.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

首次初始化且数据库中没有用户时，会生成 `admin` 管理员账号，并在终端输出随机初始密码。

如果忘记管理员密码：

```bash
cd backend
python scripts/reset_admin_password.py
```

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
http://localhost:5173
```

## 图片目录

```text
data/incoming/
  宁波市/
    2026-08-09/
      example.jpg
```

目录中的日期会作为 `orders.signing_date`。

如果本机没有 OCR，可以为图片放同名 `.txt` 调试：

```text
example.jpg
example.txt
```

## 大模型配置

默认不开启大模型，问答会使用本地规则解析。开启后，大模型只负责解析查询意图，后端仍然负责 SQL 生成、参数绑定和城市权限过滤。

DeepSeek 示例：

```text
HOME_FLOW_LLM_ENABLED=true
HOME_FLOW_LLM_PROVIDER=deepseek
HOME_FLOW_LLM_BASE_URL=https://api.deepseek.com
HOME_FLOW_LLM_MODEL=deepseek-chat
HOME_FLOW_LLM_API_KEY=你的API_KEY
```

通义千问 OpenAI 兼容模式示例：

```text
HOME_FLOW_LLM_ENABLED=true
HOME_FLOW_LLM_PROVIDER=qwen
HOME_FLOW_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode
HOME_FLOW_LLM_MODEL=qwen-plus
HOME_FLOW_LLM_API_KEY=你的API_KEY
```

## RAG 预留

已新增 `knowledge_documents` 表：

- `title`
- `content`
- `city`
- `tags`
- `status`

当前实现是 SQLite 关键词检索。等知识文档变多时，可以升级为 embeddings + 向量检索。
