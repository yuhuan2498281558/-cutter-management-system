# -*- coding: utf-8 -*-
"""
从地质纵断面 PDF 提取每环地层类型并导入 StratumBasicInfo。

使用方法：
  python manage.py import_stratum_pdf \
      --pdf path/to/authorized-geology-profile.pdf \
      --project 1 \
      [--dry-run]

策略：
1. 用 PyMuPDF 读取 PDF 第一页的文字坐标信息。
2. 识别 Y 轴"地层图例区域"（底部色块行），提取各地层名称及其 X 中心位置。
3. 识别环号标签（纯数字，出现在图中轴线附近）。
4. 对每个环号，找到其 X 坐标左右范围，判断该范围内覆盖了哪些地层色块。
5. 将地层名称映射到系统字典 stratum_type 的编码（code）。
6. upsert 到 StratumBasicInfo（project + ring_no 唯一）。

地层名称 → 字典编码映射表（与 init_dictionary.json 保持一致，可扩展）。
"""
import re
import sys
from collections import defaultdict

import django
from django.core.management.base import BaseCommand, CommandError


# ── 地层名称 → 系统字典 value（stratum_type 子项） ──────────────────────────
STRATUM_NAME_TO_CODE = {
    # 系统字典已有编码
    "黏土夹砂地层": "CLAY_SAND",
    "上软下硬地层": "SOFT_HARD",
    "全断面弱风化花岗岩": "WEAK_GRANITE",
    "基岩凸起地层": "BEDROCK_PROTRUSION",
    "软土地基": "SOFT_SOIL",
    "孤石": "BOULDER",
    # PDF 图例常见名称 → 就近映射
    "素填土": "SOFT_SOIL",
    "杂填土": "SOFT_SOIL",
    "填砂": "SOFT_SOIL",
    "填石": "SOFT_SOIL",
    "粉砂": "SOFT_SOIL",
    "淤泥质黏土": "SOFT_SOIL",
    "粉质黏土": "CLAY_SAND",
    "黏土": "CLAY_SAND",
    "细砂": "CLAY_SAND",
    "中砂": "CLAY_SAND",
    "残积砂质黏性土": "CLAY_SAND",
    "全强风化花岗岩": "SOFT_HARD",
    "散体状强风化花岗岩": "SOFT_HARD",
    "碎块状强风化花岗岩": "SOFT_HARD",
    "弱风化花岗岩": "WEAK_GRANITE",
    "漂石": "BOULDER",
    "辉绿岩": "WEAK_GRANITE",
    "花岗岩": "WEAK_GRANITE",
}

# 环号候选范围
RING_MIN = 1
RING_MAX = 20000


def _load_fitz():
    try:
        import fitz
        return fitz
    except ImportError:
        raise CommandError("需要安装 PyMuPDF：pip install pymupdf")


def extract_page_words(pdf_path: str):
    fitz = _load_fitz()
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    words = page.get_text("words")  # (x0, y0, x1, y1, text, block, line, word)
    width = page.rect.width
    height = page.rect.height
    doc.close()
    return words, width, height


def find_ring_labels(words, page_height):
    """
    从 words 中提取环号候选（纯数字，出现在页面中上区域，即非图例区）。
    返回 list of {ring_no, cx, cy}。
    """
    legend_y_threshold = page_height * 0.85  # 图例一般在底部 15%
    rings = []
    for x0, y0, x1, y1, text, *_ in words:
        text = text.strip()
        if not re.fullmatch(r"\d{1,5}", text):
            continue
        value = int(text)
        if not (RING_MIN <= value <= RING_MAX):
            continue
        cy = (y0 + y1) / 2
        if cy > legend_y_threshold:
            continue
        rings.append({"ring_no": value, "cx": (x0 + x1) / 2, "cy": cy})
    # 去重：同一环号保留 cx 最小的（最左侧出现位置）
    seen = {}
    for r in sorted(rings, key=lambda x: x["cx"]):
        if r["ring_no"] not in seen:
            seen[r["ring_no"]] = r
    return sorted(seen.values(), key=lambda x: x["ring_no"])


def find_stratum_legend(words, page_height):
    """
    在底部图例区找地层名称及其 X 中心坐标。
    返回 list of {name, code, cx}。
    """
    legend_y_start = page_height * 0.80
    candidates = []
    for x0, y0, x1, y1, text, *_ in words:
        text = text.strip()
        if not text or len(text) < 2:
            continue
        cy = (y0 + y1) / 2
        if cy < legend_y_start:
            continue
        # 多词地层名称在 PDF words 里往往是单字分割的，需要在 find_stratum_regions 阶段重组
        for name in STRATUM_NAME_TO_CODE:
            if text in name or name in text:
                candidates.append({
                    "name": name,
                    "code": STRATUM_NAME_TO_CODE[name],
                    "cx": (x0 + x1) / 2,
                    "cy": cy,
                    "text_found": text,
                })
    # 去重（同一 code 保留最靠左的）
    seen = {}
    for c in sorted(candidates, key=lambda x: x["cx"]):
        if c["code"] not in seen:
            seen[c["code"]] = c
    return list(seen.values())


def assign_stratums_to_rings(ring_labels, legend_items, page_width):
    """
    根据环号 X 坐标和图例条目 X 坐标，判断每环跨越了哪些地层。

    简化策略：
    - 图例按 cx 排序，代表横向从左到右的地层分区。
    - 相邻环号之间的 X 范围内，落入哪些图例分区就认定为该地层。
    - 每环至少保留自身最近的一个地层。
    """
    if not ring_labels or not legend_items:
        return {}

    legend_sorted = sorted(legend_items, key=lambda x: x["cx"])
    rings_sorted = sorted(ring_labels, key=lambda x: x["cx"])

    # 建立 legend 分区边界（Voronoi 式）
    boundaries = []
    for i, leg in enumerate(legend_sorted):
        left = legend_sorted[i - 1]["cx"] if i > 0 else 0
        right = legend_sorted[i + 1]["cx"] if i < len(legend_sorted) - 1 else page_width
        boundaries.append({
            "code": leg["code"],
            "name": leg["name"],
            "left": (left + leg["cx"]) / 2,
            "right": (leg["cx"] + right) / 2,
        })

    result = {}
    for ring in rings_sorted:
        ring_no = str(ring["ring_no"])
        # 当前环 X 范围：前后两个环号中间各取一半
        idx = rings_sorted.index(ring)
        prev_cx = rings_sorted[idx - 1]["cx"] if idx > 0 else 0
        next_cx = rings_sorted[idx + 1]["cx"] if idx < len(rings_sorted) - 1 else page_width
        ring_left = (prev_cx + ring["cx"]) / 2
        ring_right = (ring["cx"] + next_cx) / 2

        codes = []
        for b in boundaries:
            # 地层分区与环范围有重叠
            if b["right"] > ring_left and b["left"] < ring_right:
                if b["code"] not in codes:
                    codes.append(b["code"])

        if not codes:
            # 找最近的图例
            nearest = min(boundaries, key=lambda b: abs((b["left"] + b["right"]) / 2 - ring["cx"]))
            codes = [nearest["code"]]

        result[ring_no] = codes

    return result


class Command(BaseCommand):
    help = "从地质纵断面 PDF 提取每环地层类型并导入 StratumBasicInfo"

    def add_arguments(self, parser):
        parser.add_argument("--pdf", required=True, help="PDF 文件路径")
        parser.add_argument("--project", required=True, type=int, help="项目 ID（ProjectInfo.id）")
        parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写入数据库")

    def handle(self, *args, **options):
        from pathlib import Path
        from application.shield.models import StratumBasicInfo, ProjectInfo

        pdf_path = options["pdf"]
        project_id = options["project"]
        dry_run = options["dry_run"]

        if not Path(pdf_path).exists():
            raise CommandError(f"PDF 文件不存在: {pdf_path}")

        try:
            project = ProjectInfo.objects.get(pk=project_id)
        except ProjectInfo.DoesNotExist:
            raise CommandError(f"ProjectInfo id={project_id} 不存在")

        self.stdout.write(f"读取 PDF: {pdf_path}")
        words, page_width, page_height = extract_page_words(pdf_path)
        self.stdout.write(f"页面尺寸: {page_width:.1f} x {page_height:.1f}")

        ring_labels = find_ring_labels(words, page_height)
        self.stdout.write(f"识别环号: {len(ring_labels)} 个，范围 "
                          f"{min(r['ring_no'] for r in ring_labels) if ring_labels else '-'} ~ "
                          f"{max(r['ring_no'] for r in ring_labels) if ring_labels else '-'}")

        legend_items = find_stratum_legend(words, page_height)
        self.stdout.write(f"识别图例地层: {len(legend_items)} 种: "
                          f"{[x['name'] for x in legend_items]}")

        if not ring_labels:
            raise CommandError("未识别到环号，请检查 PDF 文件或调整参数")

        ring_stratum_map = assign_stratums_to_rings(ring_labels, legend_items, page_width)

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY RUN，以下为预览 ==="))
            for ring_no, codes in sorted(ring_stratum_map.items(), key=lambda x: int(x[0])):
                self.stdout.write(f"  环 {ring_no}: {codes}")
            return

        created = updated = 0
        for ring_no, codes in ring_stratum_map.items():
            codes_str = ",".join(codes)
            obj, is_created = StratumBasicInfo.objects.update_or_create(
                project=project,
                ring_no=ring_no,
                defaults={
                    "stratum_type_codes": codes_str,
                    "stratum_info": "",
                },
            )
            if is_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"导入完成：新建 {created} 条，更新 {updated} 条，共 {created + updated} 环"
        ))
