# home-flow 大模型相关代码说明

这份文档用于复习 home-flow 中“大模型问答 + SQL 查询 + RAG 知识库”的核心代码。重点不是逐行背代码，而是理解调用链、边界控制和面试时可以怎么讲。

## 1. 整体调用链

用户在 PC 或 H5 的智能问答入口提问后，后端链路如下：

```text
POST /api/qa/ask
  -> answer_question()
    -> retrieve_context()      # 从知识库检索 RAG 上下文
    -> generate_sql_with_llm() # 调大模型把问题转 SQL
    -> _validate_sql_payload() # 校验 SQL 安全
    -> _execute_sql()          # 只查询 allowed_orders CTE
    -> summarize_answer_with_llm()
    -> 返回 answer / data / chart / rag_context
```

知识库上传链路如下：

```text
POST /api/qa/knowledge
  -> create_knowledge_document()
    -> PDF/图片/文本提取文字
    -> 新版知识入库
    -> 旧版 active 知识归档
    -> split_chunks()
    -> 写入 knowledge_chunks
```

## 2. 大模型配置

文件：[backend/app/core/config.py](/D:/project/AI/德佑涌盛/backend/app/core/config.py)

```python
load_local_env(BACKEND_DIR / "llm_keys.env")
load_local_env(BACKEND_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        self.llm_enabled = os.getenv("HOME_FLOW_LLM_ENABLED", "false").lower() == "true"
        self.llm_provider = os.getenv("HOME_FLOW_LLM_PROVIDER", "deepseek")
        self.llm_api_key = os.getenv("HOME_FLOW_LLM_API_KEY", "")
        self.llm_base_url = os.getenv("HOME_FLOW_LLM_BASE_URL", "https://api.deepseek.com")
        self.llm_model = os.getenv("HOME_FLOW_LLM_MODEL", "deepseek-chat")
        self.llm_timeout_seconds = float(os.getenv("HOME_FLOW_LLM_TIMEOUT_SECONDS", "30"))

        # Reserved for the later admin-managed cost-control settings page.
        self.llm_daily_user_limit = int(os.getenv("HOME_FLOW_LLM_DAILY_USER_LIMIT", "0"))
        self.llm_daily_token_limit = int(os.getenv("HOME_FLOW_LLM_DAILY_TOKEN_LIMIT", "0"))
        self.llm_max_input_chars = int(os.getenv("HOME_FLOW_LLM_MAX_INPUT_CHARS", "0"))
        self.llm_max_output_tokens = int(os.getenv("HOME_FLOW_LLM_MAX_OUTPUT_TOKENS", "0"))
```

说明：

- `llm_keys.env` 用来保存本地或服务器上的 API Key，不提交 GitHub。
- 当前模型通过 OpenAI-compatible 方式接入，所以千问、智谱 GLM、DeepSeek 这类兼容接口都可以通过 `base_url + model + api_key` 配置。
- 成本控制参数已经预留，但目前没有拦截请求，后续可以迁移到“系统设置”由管理员维护。

面试可以这样讲：

> 我没有把 key 写死在代码里，而是通过本地 env 文件注入。配置层预留了 provider、base_url、model、timeout 和成本控制字段，便于从 DeepSeek 切到 GLM 或千问，也方便后续做管理员可配置的限额策略。

## 3. LangChain 大模型封装

文件：[backend/app/services/llm_service.py](/D:/project/AI/德佑涌盛/backend/app/services/llm_service.py)

### 3.1 Prompt：让大模型生成 SQL

```python
SQL_PROMPT = """
You are the SQL generator for home-flow.
Return JSON only. Do not add explanations.

The backend already applies RBAC and city filtering through a read-only CTE named allowed_orders.
You must query ONLY from allowed_orders.

Available columns:
ID, city, area, street, residential, room_number, acreage, list_price, price,
agent, store, signing_date, CA, creator, create_time, modifier, modify_time,
maintainor, maintainor_store, parking, status, remark, location, brand.

Rules:
- SQL must be a single SELECT statement.
- Use ? placeholders for all dynamic values.
- Do not include city/status filters; backend has already applied them.
- Do not use INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, ATTACH, DETACH.
- Do not query orders, users, auth_sessions, sqlite_master, or any table except allowed_orders.
- Keep result rows at or below 50 unless the user explicitly asks for more.
""".strip()
```

说明：

- 大模型不直接接触真实 `orders` 表，只能查询后端构造的 `allowed_orders`。
- Prompt 明确要求 JSON 输出，结构包含 `sql`、`params`、`chart`。
- 动态值必须走 `?` 占位符，避免模型把用户输入拼进 SQL 字符串。

面试可以这样讲：

> 这里我没有让模型拥有“随便查数据库”的能力，而是把模型限制在一个只读 CTE 上，并要求输出参数化 SQL。后端再做二次校验，这样模型只是 SQL 生成器，不是数据库执行者。

### 3.2 Prompt：让大模型总结答案

```python
ANSWER_PROMPT = """
You are home-flow's Chinese business analyst.
Answer the user's question in concise Chinese based only on the SQL result JSON and rag_context.
SQL rows are transaction data. rag_context is uploaded knowledge such as community basics, school district information, and text extracted from PDFs or images.
If SQL rows are empty but rag_context is relevant, answer from rag_context and mention the knowledge title/source.
If both SQL rows and rag_context are empty, say no matching internal data was found.
For ranking results, name the top item and include its count. Add one short insight if useful.
When uploaded knowledge conflicts, the context has already been filtered to active latest documents, so treat later active knowledge as authoritative.
Do not invent data.
""".strip()
```

说明：

- 回答阶段同时拿到 SQL 结果和 RAG 上下文。
- 如果成交数据为空但知识库命中，可以回答知识库内容。
- 如果都没有数据，明确告诉用户没有内部数据，避免幻觉。

### 3.3 构建 LangChain Chat Model

```python
def _build_chat_model():
    provider = settings.llm_provider.lower()
    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=_normalize_openai_base_url(settings.llm_base_url),
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
```

说明：

- DeepSeek 使用 `langchain-deepseek`。
- 其他兼容 OpenAI 协议的模型使用 `langchain-openai`，GLM、千问兼容接口可以走这条分支。
- `temperature=0` 是为了让 SQL 生成更稳定。

### 3.4 统一调用大模型

```python
def call_llm(messages: list[dict[str, str]], json_mode: bool = True) -> str | None:
    if not llm_is_configured():
        return None

    try:
        model = _build_chat_model()
        if json_mode and hasattr(model, "bind"):
            model = model.bind(response_format={"type": "json_object"})
        response = model.invoke([(message["role"], message["content"]) for message in messages])
        return _message_content(response).strip()
    except Exception:
        return None
```

说明：

- 如果没有配置 API Key，直接返回 `None`，业务层会走规则兜底。
- SQL 生成时开启 JSON mode；答案总结时不开 JSON mode。
- 当前异常被吞掉并返回 `None`，好处是不影响系统可用性；坏处是排查问题时日志不足，后续可以补日志记录。

面试可以这样讲：

> 我把大模型调用封装成一个统一函数，上层只关心输入 messages 和是否需要 JSON 输出。模型异常不会把问答接口打挂，而是降级到规则 SQL 和模板答案。

### 3.5 大模型生成 SQL

```python
def generate_sql_with_llm(question: str, rag_context: list[dict] | None = None) -> dict[str, Any] | None:
    content = call_llm(
        [
            {"role": "system", "content": SQL_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "rag_context": rag_context or []},
                    ensure_ascii=False,
                ),
            },
        ],
        json_mode=True,
    )
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
```

说明：

- 用户问题和检索到的知识上下文一起传给模型。
- 模型输出必须能被 `json.loads` 解析，否则视为失败。
- 真正执行 SQL 前，还会在 `qa_service.py` 做安全校验。

### 3.6 大模型总结答案

```python
def summarize_answer_with_llm(question: str, sql: str, rows: list[dict], rag_context: list[dict] | None = None) -> str | None:
    content = call_llm(
        [
            {"role": "system", "content": ANSWER_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "sql": sql,
                        "rows": rows[:50],
                        "rag_context": rag_context or [],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        json_mode=False,
    )
    return content.strip() if content else None
```

说明：

- 只把前 50 行结果给模型，避免上下文过长。
- 模型负责“组织语言”，不负责重新查询数据库。

## 4. 问答编排服务

文件：[backend/app/services/qa_service.py](/D:/project/AI/德佑涌盛/backend/app/services/qa_service.py)

### 4.1 SQL 安全校验

```python
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|pragma|attach|detach|replace|truncate|vacuum|grant|revoke)\b",
    re.IGNORECASE,
)


def _validate_sql_payload(payload: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not payload:
        return None, "llm_returned_empty"
    sql = str(payload.get("sql") or "").strip()
    params = payload.get("params") or []
    if not sql or not sql.lower().startswith("select"):
        return None, "llm_sql_not_select"
    if ";" in sql or FORBIDDEN_SQL.search(sql):
        return None, "llm_sql_forbidden"
    lowered = sql.lower()
    if "allowed_orders" not in lowered:
        return None, "llm_sql_missing_allowed_orders"
    blocked_sources = [" orders", " users", " auth_sessions", " sqlite_master", " sqlite_schema"]
    if any(source in lowered for source in blocked_sources):
        return None, "llm_sql_blocked_source"
    if not isinstance(params, list):
        return None, "llm_params_not_list"
    return {
        "sql": sql,
        "params": params,
        "chart": payload.get("chart") or {"type": "none"},
        "source": "llm",
    }, None
```

说明：

- 只允许 `SELECT`。
- 禁止分号，避免多语句执行。
- 禁止 DDL/DML 关键词。
- 必须查询 `allowed_orders`，不能直接查真实表。
- 参数必须是数组。

面试可以这样讲：

> 大模型生成 SQL 是高风险点，所以我做了“双层限制”：Prompt 限制模型只能输出 allowed_orders 查询，后端再用正则和白名单校验，最后执行时通过参数绑定传值。

### 4.2 后端构造 RBAC 查询边界

```python
def _execute_sql(conn, sql_payload: dict[str, Any], city: str) -> list[dict]:
    secured_sql = f"""
    WITH allowed_orders AS (
        SELECT *
        FROM orders
        WHERE city = ? AND COALESCE(status, 'normal') = 'normal'
    )
    {sql_payload["sql"]}
    """
    rows = conn.execute(secured_sql, tuple([city] + sql_payload["params"])).fetchall()
    return rows_to_dicts(rows)
```

说明：

- 城市权限不交给模型判断，而是后端强制注入。
- 模型只能在 `allowed_orders` 上查，天然继承城市和状态过滤。

当前版本中，店员和店长都是按城市看成交数据；如果后续 RBAC 更细，可以在这个 CTE 里继续加门店、角色、数据范围条件。

### 4.3 大模型失败时的规则兜底

```python
def _choose_sql_payload(question: str, rag_context: list[dict]) -> tuple[dict[str, Any], str | None]:
    if not llm_is_configured():
        return _fallback_sql(question), "llm_not_configured"

    llm_payload = generate_sql_with_llm(question, rag_context)
    sql_payload, validation_error = _validate_sql_payload(llm_payload)
    if sql_payload:
        return sql_payload, None
    return _fallback_sql(question), validation_error or "llm_sql_invalid"
```

说明：

- 优先让大模型生成 SQL。
- 如果模型没配置、返回空、JSON 解析失败、SQL 校验失败，就走规则 SQL。
- 这保证系统不是“模型挂了就不可用”。

### 4.4 主函数 answer_question

```python
def answer_question(conn, question: str, city: str) -> dict:
    clean_question = question.strip()
    rag_context = retrieve_context(conn, clean_question, city)

    sql_payload, fallback_reason = _choose_sql_payload(clean_question, rag_context)
    try:
        rows = _execute_sql(conn, sql_payload, city)
    except Exception:
        fallback_reason = "llm_sql_execution_failed" if sql_payload["source"] == "llm" else "fallback_sql_execution_failed"
        sql_payload = _fallback_sql(clean_question)
        rows = _execute_sql(conn, sql_payload, city)

    answer = summarize_answer_with_llm(clean_question, sql_payload["sql"], rows, rag_context)
    answer_source = "llm" if answer else "fallback"
    if not answer:
        answer = _fallback_answer(clean_question, rows, rag_context)

    return {
        "answer": answer,
        "answer_source": answer_source,
        "data": rows,
        "sql": sql_payload["sql"],
        "sql_params": sql_payload["params"],
        "sql_source": sql_payload["source"],
        "llm_fallback_reason": fallback_reason,
        "llm_config": llm_config_summary(),
        "chart": _chart_from_payload(sql_payload, rows),
        "rag_context": rag_context,
    }
```

说明：

- `retrieve_context` 先拿知识库上下文。
- `_choose_sql_payload` 优先大模型生成 SQL。
- `_execute_sql` 执行受限查询。
- `summarize_answer_with_llm` 让模型基于结果做中文总结。
- 返回值里保留 SQL、参数、图表配置、RAG 上下文，方便前端展示和后续排查。

## 5. RAG 检索逻辑

文件：[backend/app/services/rag_service.py](/D:/project/AI/德佑涌盛/backend/app/services/rag_service.py)

```python
def _keywords(question: str) -> list[str]:
    segments = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question)
    keywords: list[str] = []
    for segment in segments:
        if segment not in keywords:
            keywords.append(segment)
        if len(segment) > 8:
            for size in (4, 3, 2):
                for index in range(0, len(segment) - size + 1):
                    token = segment[index : index + size]
                    if token not in keywords:
                        keywords.append(token)
                    if len(keywords) >= 12:
                        return keywords
    return keywords[:12]
```

说明：

- 当前 RAG 是轻量关键词检索，不是向量库。
- 对中文连续文本做 2-4 字切分，提升“无空格中文问题”的命中概率。

```python
def retrieve_context(conn, question: str, city: str, limit: int = 5) -> list[dict]:
    keywords = _keywords(question)
    if not keywords:
        return []

    clauses = ["kd.status = 'active'", "kc.status = 'active'", "(kd.city IS NULL OR kd.city = ?)"]
    params: list[str] = [city]
    like_clauses = []
    for keyword in keywords:
        like_clauses.append("(kd.title LIKE ? OR kc.content LIKE ? OR kd.tags LIKE ? OR kd.community_name LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    clauses.append("(" + " OR ".join(like_clauses) + ")")
    params.append(str(limit))
    rows = conn.execute(
        f"""
        SELECT kd.id, kd.title, kc.content, kd.tags, kd.community_name, kd.knowledge_type,
               kd.source_type, kd.source_file, kd.version, kd.create_time
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        WHERE {' AND '.join(clauses)}
        ORDER BY kd.create_time DESC, kc.chunk_index ASC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return rows_to_dicts(rows)
```

说明：

- 只检索 `active` 文档和 `active` 分块。
- 城市隔离在检索时生效。
- 按 `create_time DESC` 排序，所以新知识优先。

面试可以这样讲：

> 这个阶段我没有直接上向量数据库，而是先做轻量 RAG：上传资料分块，提问时用关键词 LIKE 检索 active chunk。业务数据量小、知识资料规模也不大，先把闭环跑通。后续如果知识库变大，可以替换为 embedding + vector store，`retrieve_context` 这个函数就是扩展点。

## 6. 知识库上传与分块

文件：[backend/app/services/knowledge_service.py](/D:/project/AI/德佑涌盛/backend/app/services/knowledge_service.py)

### 6.1 支持 PDF、图片、文本

```python
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PDF_EXTENSIONS = {".pdf"}


def _extract_upload_text(file: UploadFile | None, file_content: bytes | None) -> tuple[str, str | None, str | None]:
    if file is None or not file.filename or not file_content:
        return "", None, None

    suffix = Path(file.filename).suffix.lower()
    file_path = _write_file(file.filename, file_content)

    if suffix in PDF_EXTENSIONS:
        return _extract_pdf_text(file_content), "pdf", str(file_path)
    if suffix in IMAGE_EXTENSIONS:
        text, error = extract_text(file_path)
        if error:
            raise ValueError(error)
        return text, "image", str(file_path)
    if suffix in {".txt", ".md"}:
        return file_content.decode("utf-8", errors="ignore"), "text", str(file_path)
    raise ValueError("仅支持上传 PDF、图片、txt 或 md 文件。")
```

说明：

- PDF 用 `pypdf` 提取可复制文字。
- 图片复用现有 OCR：`image_import_service.extract_text`，当前优先 RapidOCR。
- 文本文件直接 UTF-8 解码。

### 6.2 文档分块

```python
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


def split_chunks(content: str) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", content).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_SIZE)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(0, end - CHUNK_OVERLAP)
    return chunks
```

说明：

- 每块 900 字，重叠 120 字。
- 重叠是为了避免关键信息刚好被切断。

### 6.3 新版覆盖旧版

```python
scope_where = "city = ? AND COALESCE(community_name, '') = ? AND knowledge_type = ? AND status = 'active'"
scope_params = (user.city, community_name or "", knowledge_type)
latest = conn.execute(
    "SELECT MAX(version) AS version FROM knowledge_documents WHERE city = ? AND COALESCE(community_name, '') = ? AND knowledge_type = ?",
    scope_params,
).fetchone()
version = int((latest["version"] if latest else 0) or 0) + 1

old_rows = conn.execute(f"SELECT id FROM knowledge_documents WHERE {scope_where}", scope_params).fetchall()
old_ids = [row["id"] for row in old_rows]
if old_ids:
    placeholders = ",".join("?" for _ in old_ids)
    conn.execute(
        f"UPDATE knowledge_documents SET status = 'archived', archived_time = CURRENT_TIMESTAMP, modify_time = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        tuple(old_ids),
    )
    conn.execute(
        f"UPDATE knowledge_chunks SET status = 'archived' WHERE document_id IN ({placeholders})",
        tuple(old_ids),
    )
```

说明：

- 同一城市、同一楼盘、同一知识类型，如果上传新版，就把旧版归档。
- 检索只查 active，所以冲突知识以最新版为准。

面试可以这样讲：

> 冲突处理我没有做审核流，而是用了版本化 + 归档策略。业务规则是最新版为准，所以新上传知识会使旧 active 文档和 chunk 变 archived，检索层天然只看到最新版本。

## 7. 问答 API 入口

文件：[backend/app/api/qa.py](/D:/project/AI/德佑涌盛/backend/app/api/qa.py)

```python
@router.post("/ask")
def ask(body: AskRequest, user: CurrentUser = Depends(current_user)) -> dict:
    with get_connection() as conn:
        result = answer_question(conn, body.question, user.city)
        session_id = body.session_id
        if session_id is None:
            cursor = conn.execute(
                "INSERT INTO chat_sessions(user_id, title) VALUES (?, ?)",
                (user.id, body.question[:40]),
            )
            session_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO chat_messages(session_id, user_id, role, content, result_json)
            VALUES (?, ?, 'user', ?, ?)
            """,
            (session_id, user.id, body.question, json.dumps(result, ensure_ascii=False)),
        )
        conn.execute(
            """
            INSERT INTO chat_messages(session_id, user_id, role, content, result_json)
            VALUES (?, ?, 'assistant', ?, ?)
            """,
            (session_id, user.id, result["answer"], json.dumps(result, ensure_ascii=False)),
        )
        conn.commit()
        result["session_id"] = session_id
        return result
```

说明：

- 当前用户来自 `current_user`，不是前端传用户 ID。
- 调用 `answer_question` 时只传 `user.city`，后端用城市做数据隔离。
- 用户问题和 AI 回复都会写入 `chat_messages`，方便后续做历史会话。

```python
@router.post("/knowledge")
async def upload_knowledge(
    title: str = Form(...),
    knowledge_type: str = Form("楼盘信息"),
    community_name: str | None = Form(None),
    content: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(current_user),
) -> dict:
    file_content = await file.read() if file else None
    with get_connection() as conn:
        try:
            result = create_knowledge_document(
                conn,
                user,
                title=title,
                community_name=community_name,
                knowledge_type=knowledge_type,
                content=content,
                file=file,
                file_content=file_content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.commit()
        return result
```

说明：

- 知识上传走 multipart form。
- 店员、店长、管理员都可以上传。
- 上传失败时返回 400，并把可理解的错误原因给前端。

## 8. 数据表设计

文件：[backend/app/db/migrations.py](/D:/project/AI/德佑涌盛/backend/app/db/migrations.py)

```sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT,
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modify_time TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    user_id INTEGER,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    query_json TEXT,
    result_json TEXT,
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

说明：

- `chat_sessions` 存一次会话。
- `chat_messages` 存用户消息和助手消息。
- `result_json` 存完整问答结果，便于排查 SQL、图表配置和 RAG 命中。

```sql
CREATE TABLE IF NOT EXISTS knowledge_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    city TEXT,
    tags TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    modify_time TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    city TEXT,
    community_name TEXT,
    knowledge_type TEXT,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    create_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(document_id) REFERENCES knowledge_documents(id)
);
```

说明：

- `knowledge_documents` 是知识文档主表。
- `knowledge_chunks` 是分块表，RAG 检索主要查这里。
- 迁移里又给 `knowledge_documents` 增加了 `community_name`、`knowledge_type`、`source_type`、`source_file`、`file_path`、`uploader_user_id`、`version`、`archived_time` 等字段。

## 9. 当前方案的优点和不足

优点：

- 接入方式灵活：DeepSeek 走专用 LangChain 包，GLM/千问走 OpenAI-compatible。
- 安全边界清晰：模型只生成 SQL，后端校验和执行。
- 可降级：模型不可用时走规则 SQL 和模板答案。
- 知识库闭环完整：上传、抽取、分块、检索、回答。
- 数据权限后端控制：城市过滤不依赖模型。

不足和后续优化：

- 现在 RAG 是关键词 LIKE 检索，不是 embedding 向量检索。
- `call_llm` 捕获异常后没有记录日志，后续排障不够方便。
- SQL 校验是规则校验，后续可以引入 SQL parser 做更强的 AST 校验。
- 成本控制只预留了配置字段，还没有按用户/日期统计调用量。
- 会话历史已经存储，但目前没有完整的多轮上下文传给模型。

## 10. 面试回答模板

可以这样概括：

> 这个项目的智能问答分两类数据来源：一类是结构化成交数据，一类是用户上传的楼盘、学区等非结构化知识。用户提问后，系统先从知识库检索相关 chunk 作为 RAG 上下文，然后调用大模型把问题转成参数化 SQL。为了安全，模型只能查询后端提供的 `allowed_orders` CTE，真正的城市权限和正常状态过滤由后端强制加上。SQL 生成后还会做只读、禁用危险关键字、禁止直接查真实表等校验。执行结果和 RAG 上下文再交给大模型生成中文答案。如果模型不可用或 SQL 不合法，就降级到规则 SQL 和模板答案，保证系统可用。

如果面试官追问“为什么没直接上向量库”，可以回答：

> 当前业务数据量和知识库规模都不大，先用 SQLite + 分块 + 关键词检索完成最小闭环。系统把 RAG 检索封装在 `retrieve_context`，后续替换成 embedding 和向量数据库时，问答编排层不用大改。
