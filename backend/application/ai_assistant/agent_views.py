"""只供模型阅读的工具结果：保留全量统计，明细分页并去除重复长文本。"""

import json


AGENT_PAGE_SIZE = 20


def agent_view(raw, page=1, page_size=AGENT_PAGE_SIZE):
    """page_size=None 时只去重，不分页。"""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(data, dict) or "error" in data:
        return raw

    paging = {}
    seen = set()

    def _visit(node, path):
        if isinstance(node, dict):
            return {key: _visit(value, f"{path}.{key}" if path else key)
                    for key, value in node.items()}
        if isinstance(node, list):
            if page_size is not None and len(node) > page_size and all(isinstance(row, dict) for row in node):
                total = len(node)
                paging[path] = {"total": total, "page": page, "page_size": page_size,
                                "has_more": page * page_size < total}
                node = node[(page - 1) * page_size:page * page_size]
            # 只在本页可见内容中去重，避免引用已经被分页移出的文字。
            return [_visit(value, f"{path}.{index}") for index, value in enumerate(node)]
        if isinstance(node, str) and len(node) >= 40:
            if node in seen:
                return "（同上）"
            seen.add(node)
        return node

    result = _visit(data, "")
    if paging:
        result["_paging"] = paging
        result["_paging_note"] = (
            f"列表只给了第{page}页（每页{page_size}条），各列表总数见 _paging。"
            f"需要后面的记录时，用相同参数加 page={page + 1} 再查。"
        )
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
