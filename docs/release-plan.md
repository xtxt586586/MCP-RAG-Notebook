# 发布准备与提交计划

发布改动按实际变更拆分为下列提交：

1. `feat: harden knowledge-base retrieval and citations`：检索、引用及相关测试。
2. `feat: add reproducible knowledge-base demo and evaluation`：演示资料、真实模型评测及报告。
3. `build: document and automate clean deployment`：Compose、模型准备、部署脚本和说明。

已有远程地址通过 `git remote -v` 查看；在新克隆中也可用 `git remote add origin <你的仓库地址>` 设置。发布前检查 `git status --short`、`git diff --check`、实际追踪文件、许可证和密钥扫描结果；不要提交 `.env`、模型缓存、私有文档或数据库。

`sample.pdf`、`sample.png` 是历史样例，不属于当前虚构演示数据；它们已从最新快照中移除，原本地文件保留且已忽略。旧提交仍包含这两个文件；项目所有者已确认两份文件可以公开。仅从最新提交移除不会清除历史。

问答冒烟用例验证的是指定示例上的输出，并非生产质量保证。当前 30 条切片标注来自三篇虚构文档，不是独立的真实业务测试集，不应将其结果宣传为现实场景的检索效果。
