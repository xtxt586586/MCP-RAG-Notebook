# MCP-RAG-Notebook

个人知识管理与知识库问答项目。文档上传后由 Celery 异步解析和建立向量索引；检索使用 BGE-M3、Milvus 稠密/稀疏召回和 RRF 融合，可选 BGE Reranker。系统还包含笔记、知识图谱、MCP 工具和 AI 写作功能。

> 当前项目仍在进行可复现部署和端到端验收。以下为本地开发配置，不代表生产环境已经完成安全加固。不要将数据库、对象存储或 MCP 服务直接暴露到公网。

## 环境要求

- Docker Desktop 或 Docker Engine + Compose；首次构建需要访问 Docker 镜像仓库、Python 和 npm 包仓库。
- BGE-M3 在本地运行，需要预留数 GB 磁盘和足够内存。首次加载和 CPU 推理可能较慢；后端与 worker 都会加载模型，内存占用会叠加。
- 文档问答、AI 写作和实体抽取需要有效的 DeepSeek API 凭据和网络连接。多模态、部分 MCP 工具另有各自依赖或凭据。
- 首次模型下载需要从 Hugging Face 及其权重分发域名下载数据；无法连接时应先准备模型文件或配置可用网络。仅能访问 Hugging Face 首页并不代表权重下载可用。

## 本地启动

1. 将 `.env.example` 复制为 `.env`，设置 `POSTGRES_PASSWORD`、`MINIO_ROOT_PASSWORD`、`JWT_SECRET_KEY` 和 `DEEPSEEK_API_KEY`。不要提交 `.env` 或公开密钥。
2. 默认 `HF_CACHE_DIR=hf_cache` 使用 Docker 管理的共享模型缓存卷；`EMBEDDING_OFFLINE=false` 允许首次下载。网络受限时，可提前准备完整模型并在容器中配置本地模型路径；确认模型可加载后再设置 `EMBEDDING_OFFLINE=true`。
3. 在项目目录执行 `docker compose up -d --build`，再用 `docker compose ps` 和 `docker compose logs --tail=100 backend celery-worker` 查看状态。后端启动时执行数据库迁移和 Milvus collection 初始化。
4. 访问 `http://127.0.0.1:3000` 注册并登录。API 地址为 `http://127.0.0.1:18765`。`/health` 仅表示 API 进程可响应，不代表模型、索引或外部 LLM 已可用；以实际上传和检索验证为准。

Compose 使用具名卷保存数据库、对象存储、向量索引和模型缓存。不要使用 `docker compose down -v`，除非明确要删除这些卷中的数据。修改 `.env` 后需重新创建受影响的容器。

## 演示数据与检索评测

项目附带三篇**虚构**资料和 30 条文档级相关性标注，用于检查评测流程；它们不是现实场景测评集，也不足以证明检索质量优于其他方案。请在独立的测试账号、空知识库中使用，不要将私有文件当作公开演示数据。

先在网页注册测试账号，然后在容器里执行（导入器要求该账号的知识库没有文档）：

```bash
docker compose exec -it backend python -m app.scripts.import_demo --email YOUR_TEST_EMAIL
```

输入密码后，脚本上传三份资料，等待索引并显示用户和知识库 ID。文件处理失败或超时会停止；已有文档不会被删除。如果导入中断，先在页面检查状态并按需重试，不要重复导入到含文档的知识库。

下载好 `BAAI/bge-reranker-v2-m3` 后，可在后端容器中以显示的 ID 运行：

```bash
docker compose exec -T backend python -m app.scripts.evaluate_retrieval \
  --user-id USER_UUID --knowledge-base-id KNOWLEDGE_BASE_UUID \
  --labels app/scripts/demo_data/retrieval_labels.json --k 1 > retrieval-report.json
```

程序比较 Dense、Hybrid 和 Hybrid + Reranker，输出文档级 Recall@K、MRR@K、每题用时及延迟中位数；模型预热不计入查询时间。它对每个问题计算一次向量，并将相同向量的耗时计入三个方案。Hybrid 和重排使用相同候选；重排加载或执行失败时直接报错，不生成伪造的对照结果。评测输出包含标注文件哈希和模型配置，但模型别名尚未固定到权重版本；要做严谨对照，应记录模型权重版本、运行环境和多轮测量结果。该流程不评估回答是否有依据、引用是否正确或无依据时是否拒答。

一次示例运行结果及其限制见 [检索对照冒烟记录](docs/retrieval-smoke-report.md)。

## 目前的边界

- 前端默认使用 Agent 自动路由；选择“仅知识库”后使用知识库问答接口，无检索结果时返回资料不足。检索命中并不保证内容足以回答，仍需通过引用和拒答评测验证模型表现。
- 示例配置关闭自动图谱抽取，以免外部模型调用阻塞单 worker 的文档索引；仍可在图谱页面手动构建，或设置 `GRAPH_AUTO_EXTRACT_ENABLED=true` 恢复自动抽取。
- 默认关闭 `fetch` MCP 服务：当前拒绝 HTTP 重定向，但 URL 解析检查仍不能完整防范 DNS 重绑定，不应在不可信网络中启用。
- 默认关闭 `filesystem` MCP 服务：其工作目录由服务进程共享，不提供按用户隔离。不要在多用户环境中启用它来访问私有文件。
- 默认 `MCP_DYNAMIC_REGISTRY_ENABLED=false`：运行时只采用受信任的 `mcp_servers/servers.json`，忽略数据库中的动态定义，并拒绝通过 API 增删改全局服务。动态配置能启动任意本地命令，启用它会允许任何已登录用户修改全局配置；仅供完全可信的单用户本地环境使用，并非管理员权限系统。
- 默认 Compose 的数据服务端口仅绑定到宿主机回环地址；前端和 API 仍监听宿主机网络，公网部署需要另行配置网络隔离、TLS、访问控制、备份与密钥管理。
- 此仓库尚未提供经人工独立复核的真实任务评测集、完整的引用/拒答评测报告或并发压测结果。
