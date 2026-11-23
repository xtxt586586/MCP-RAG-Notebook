#!/usr/bin/env python3
"""Import an isolated demo corpus and query the running real RAG service."""
import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = [
    {"id": "library", "question": "星桥社区图书馆普通读者最多能借几本纸质图书？借期多久？", "document": "library.md", "terms": [["五", "5"], ["二十八", "28"]]},
    {"id": "shipping", "question": "云舟商城订单实付款满多少元免标准运费？", "document": "shipping.md", "terms": [["九十九", "99"]]},
    {"id": "workshop", "question": "青杉工作坊迟到者的名额会自动转给候补吗？", "document": "workshop.md", "terms": [["不会", "不自动", "不会自动", "不因迟到"]]},
    {"id": "unanswerable", "question": "星桥社区图书馆管理员的月薪是多少？", "document": "library.md", "refusal": ["无法", "没有", "未提供", "未提及", "未说明", "不知道", "不能确定", "不足"]},
]


def request(base, method, path, *, token=None, payload=None, upload=None, timeout=180):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if upload:
        name, kb_id = upload
        boundary = "demo" + secrets.token_hex(12)
        content = (ROOT / "data" / name).read_bytes()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="knowledge_base_id"\r\n\r\n{kb_id}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                'Content-Type: text/markdown\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(base.rstrip("/") + "/api/v1" + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}") from exc


def run(base, selected, timeout):
    email = f"demo-{secrets.token_hex(10)}@example.com"
    password = secrets.token_urlsafe(24) + "A1"
    token = request(base, "POST", "/auth/register", payload={"email": email, "password": password})["access_token"]
    kb = request(base, "GET", "/knowledge-bases/current", token=token)["id"]
    print("已创建独立演示账号并导入三份虚构资料。", flush=True)
    ids = {}
    for name in ("library.md", "shipping.md", "workshop.md"):
        ids[name] = request(base, "POST", "/documents/upload", token=token, upload=(name, kb))["id"]
    deadline = time.monotonic() + timeout
    pending = dict(ids)
    while pending and time.monotonic() < deadline:
        for name, doc_id in list(pending.items()):
            status = request(base, "GET", f"/documents/{doc_id}", token=token)["status"]
            if status == "READY":
                print(f"索引完成：{name}", flush=True)
                del pending[name]
            elif status.endswith("FAILED"):
                raise RuntimeError(f"{name} 处理失败：{status}；请查看 worker 日志")
        if pending:
            time.sleep(3)
    if pending:
        raise TimeoutError(f"索引超时：{', '.join(pending)}")
    results = []
    for case in selected:
        start = time.monotonic()
        response = request(base, "POST", "/chat", token=token, payload={"knowledge_base_id": kb, "question": case["question"], "require_sources": True}, timeout=180)
        answer = response["answer"]
        sources = response.get("sources", [])
        source_ok = any(s.get("file_name") == case["document"] or s.get("title") == case["document"] for s in sources)
        answer_ok = (any(term in answer for term in case["refusal"]) if "refusal" in case else all(any(term in answer for term in alternatives) for alternatives in case["terms"]))
        # A knowledge-only no-retrieval fallback can be generated without an LLM.
        model_called = response.get("retrieval_mode") in ("hybrid", "graph", "hybrid_graph")
        passed = answer_ok and source_ok and model_called
        assertion = {"source": case["document"], "answer_terms_any": case.get("terms"), "refusal_terms_any": case.get("refusal"), "requires_model_route": True}
        result = {"id": case["id"], "question": case["question"], "expected_document": case["document"], "assertion": assertion, "sources": [{k: s.get(k) for k in ("citation", "file_name", "chunk_index", "page_number")} for s in sources], "answer": answer, "retrieval_mode": response.get("retrieval_mode"), "passed": passed, "seconds": round(time.monotonic() - start, 2)}
        results.append(result)
        print(f"\n问题：{case['question']}\n来源：{json.dumps(result['sources'], ensure_ascii=False)}\n回答：{answer}\n{'通过' if passed else '未通过'} · {result['seconds']} 秒", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18765")
    parser.add_argument("--timeout", type=int, default=1800, help="Maximum seconds to wait for indexing")
    parser.add_argument("--eval", action="store_true", help="Run all four cases, including an unanswerable question")
    parser.add_argument("--report", type=Path, help="Write an evaluation report in Markdown")
    parser.add_argument("--model-label", default="后端配置的 DeepSeek 模型", help="Operator-provided model name for the report")
    args = parser.parse_args()
    try:
        results = run(args.base_url, CASES if args.eval else CASES[:3], args.timeout)
        if args.report:
            lines = ["# 真实知识库问答评测", "", f"运行时间：{datetime.now(timezone.utc).isoformat()}；模型：{args.model_label}（由运行者填写，脚本不查询服务配置）。", "", "通过知识库 API 上传演示资料并请求回答；每题独立会话。耗时包括检索与模型请求，不包含导入索引。", ""]
            for item in results:
                lines += [f"## {item['id']} — {'通过' if item['passed'] else '未通过'}", "", f"- 问题：{item['question']}", f"- 期望文档：{item['expected_document']}", f"- 断言：`{json.dumps(item['assertion'], ensure_ascii=False)}`", f"- 返回来源：`{json.dumps(item['sources'], ensure_ascii=False)}`", f"- 检索模式：{item['retrieval_mode']}", f"- 耗时：{item['seconds']} 秒", "", f"回答：{item['answer']}", ""]
            args.report.write_text('\n'.join(lines), encoding='utf-8')
        return 0 if all(item["passed"] for item in results) else 1
    except (RuntimeError, OSError, TimeoutError, ValueError) as exc:
        print(f"演示失败：{exc}", file=sys.stderr)
        if args.report:
            try:
                args.report.write_text(f"# 真实知识库问答评测\n\n运行失败，未完成评测：{exc}\n", encoding="utf-8")
            except OSError:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
