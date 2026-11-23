# 真实知识库问答评测

运行时间：2026-11-23T12:55:12.171513+00:00；模型：deepseek-chat（由运行者填写，脚本不查询服务配置）。

通过知识库 API 上传演示资料并请求回答；每题独立会话。耗时包括检索与模型请求，不包含导入索引。

## library — 通过

- 问题：星桥社区图书馆普通读者最多能借几本纸质图书？借期多久？
- 期望文档：library.md
- 断言：`{"source": "library.md", "answer_terms_any": [["五", "5"], ["二十八", "28"]], "refusal_terms_any": null, "requires_model_route": true}`
- 返回来源：`[{"citation": "[资料1]", "file_name": "library.md", "chunk_index": 0, "page_number": null}]`
- 检索模式：hybrid
- 耗时：1.41 秒

回答：根据知识库资料，星桥社区图书馆普通读者一次最多借阅 **五本纸质图书**，借期为 **二十八天**；借期内可通过读者中心续借一次，续借十四天 [资料1]。

## shipping — 通过

- 问题：云舟商城订单实付款满多少元免标准运费？
- 期望文档：shipping.md
- 断言：`{"source": "shipping.md", "answer_terms_any": [["九十九", "99"]], "refusal_terms_any": null, "requires_model_route": true}`
- 返回来源：`[{"citation": "[资料1]", "file_name": "shipping.md", "chunk_index": 0, "page_number": null}]`
- 检索模式：hybrid
- 耗时：1.56 秒

回答：根据 [资料1]，云舟商城订单实付款满 **99 元**免标准运费；不足 99 元的订单收取 8 元标准运费。

## workshop — 通过

- 问题：青杉工作坊迟到者的名额会自动转给候补吗？
- 期望文档：workshop.md
- 断言：`{"source": "workshop.md", "answer_terms_any": [["不会", "不自动", "不会自动", "不因迟到"]], "refusal_terms_any": null, "requires_model_route": true}`
- 返回来源：`[{"citation": "[资料2]", "file_name": "workshop.md", "chunk_index": 1, "page_number": null}]`
- 检索模式：hybrid
- 耗时：1.05 秒

回答：根据知识库资料，不会。资料明确说明：迟到者可以进入教室，但可能错过开场说明；**名额不会因为迟到自动转给候补**，迟到也不会自动取消参与资格或触发候补替换 [资料2]。

## unanswerable — 通过

- 问题：星桥社区图书馆管理员的月薪是多少？
- 期望文档：library.md
- 断言：`{"source": "library.md", "answer_terms_any": null, "refusal_terms_any": ["无法", "没有", "未提供", "未提及", "未说明", "不知道", "不能确定", "不足"], "requires_model_route": true}`
- 返回来源：`[{"citation": "[资料1]", "file_name": "library.md", "chunk_index": 0, "page_number": null}, {"citation": "[资料2]", "file_name": "library.md", "chunk_index": 1, "page_number": null}, {"citation": "[资料3]", "file_name": "library.md", "chunk_index": 2, "page_number": null}, {"citation": "[资料4]", "file_name": "workshop.md", "chunk_index": 1, "page_number": null}, {"citation": "[资料5]", "file_name": "workshop.md", "chunk_index": 0, "page_number": null}]`
- 检索模式：hybrid
- 耗时：1.39 秒

回答：根据当前知识库资料无法确定。资料中只涉及星桥社区图书馆的借阅规则、读者证办理、自习室预约等内容，没有提及管理员薪酬信息。
