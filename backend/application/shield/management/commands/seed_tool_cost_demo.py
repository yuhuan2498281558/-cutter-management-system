from decimal import Decimal

from django.core.management.base import BaseCommand

from application.shield.models import ToolCost, ToolInfo


COST_LIBRARY = [
    ("福普宁刀具制造", "福普宁", Decimal("0")),
    ("恒大钻具", "易得通", Decimal("650")),
    ("中铁装备刀具中心", "中铁装备", Decimal("900")),
    ("洛阳新强联", "新强联", Decimal("1200")),
    ("江苏瑞盾工具", "瑞盾", Decimal("1450")),
    ("河南沃德刀具", "沃德", Decimal("1750")),
    ("上海隧道刀具", "隧道工匠", Decimal("2100")),
    ("武汉盾构配件", "盾虎机", Decimal("2400")),
]

REPAIR_LIBRARY = [
    ("福普宁刀具制造", "福普宁", ["刀圈", "轴承"], Decimal("480")),
    ("恒大钻具", "易得通", ["密封件", "轴承"], Decimal("620")),
    ("中铁装备刀具中心", "中铁装备", ["刀圈", "密封件"], Decimal("760")),
    ("江苏瑞盾工具", "瑞盾", ["刀圈", "密封件", "轴承"], Decimal("880")),
]


class Command(BaseCommand):
    help = "Create representative new-tool and repair cost records for every configured tool type."

    def handle(self, *args, **options):
        created = 0
        updated = 0
        tools = ToolInfo.objects.order_by("tool_parent_type", "tool_type_name", "id")
        for index, tool in enumerate(tools):
            if tool.tool_parent_type == "DISC":
                base_price = Decimal("5600")
            elif tool.tool_parent_type == "SCRAPER":
                base_price = Decimal("1600")
            else:
                base_price = Decimal("2200")

            for pair_index, (manufacturer, brand, price_offset) in enumerate(COST_LIBRARY):
                _, was_created = ToolCost.objects.update_or_create(
                    tool_info=tool,
                    cost_type="NEW_TOOL",
                    manufacturer=manufacturer,
                    brand=brand,
                    defaults={
                        "unit_price": base_price + price_offset + Decimal(index * (180 if pair_index < 2 else 140)),
                        "inventory": 0,
                        "remark": "系统生成的成本库样例，可在刀具成本库中维护",
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

            for manufacturer, brand, repair_parts, price_offset in REPAIR_LIBRARY:
                _, was_created = ToolCost.objects.update_or_create(
                    tool_info=tool,
                    cost_type="REPAIR",
                    manufacturer=manufacturer,
                    brand=brand,
                    defaults={
                        "unit_price": price_offset + Decimal(index * 35),
                        "inventory": 0,
                        "repair_parts": repair_parts,
                        "remark": "系统生成的维修成本样例，可在刀具成本库中维护",
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Tool cost samples ready: {created} created, {updated} updated, "
                f"{ToolCost.objects.filter(cost_type='NEW_TOOL').count()} new-tool records and "
                f"{ToolCost.objects.filter(cost_type='REPAIR').count()} repair records total."
            )
        )
