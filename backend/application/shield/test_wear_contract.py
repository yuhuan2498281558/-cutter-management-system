"""Shared wear semantics: unrecognized descriptions are not abnormal evidence."""
from django.db.models import Count, F
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from application.shield.models import (
    ProjectInfo, ShieldMachineBasicInfo, ToolChangeDetail, WarehouseOpeningBasicInfo,
)
from application.shield.wear import (
    KNOWN_ABNORMAL_VALUES, NORMAL_WEAR_VALUES,
    Q_WEAR_ABNORMAL, Q_WEAR_NORMAL, Q_WEAR_RECORDED,
    abnormal_rate, classify_wear_counts, is_wear_recorded, normalize_wear,
    q_wear_abnormal, q_wear_normal, q_wear_recorded, wear_display,
)


# These cases are independent expectations for the previously divergent terms.
WEAR_CASES = [
    (None, None), ('', None), (' \t\r\n\u3000', None),
    ('其他', None), ('待核实', None), ('人工纠正', None), ('无', None),
    ('NORMAL?', None), ('NO RMAL', None), ('未知异常描述', None),
    ('无异常', 'NORMAL'), ('正常磨损', 'NORMAL'), ('轻微磨损', 'NORMAL'),
    ('未见异常', 'NORMAL'), (' good ', 'NORMAL'),
    ('\tNoRmAl\r\n', 'NORMAL'), ('\u3000良好\xa0', 'NORMAL'),
    ('异常', 'ABNORMAL'), ('异常磨损', 'ABNORMAL'), ('崩口', 'ABNORMAL'),
    ('\tchip\r\n', 'ABNORMAL'), ('刀圈磨平', 'ABNORMAL'), ('刀体磨损', 'ABNORMAL'),
    *[(value, 'NORMAL') for value in NORMAL_WEAR_VALUES],
    *[(value, 'ABNORMAL') for value in KNOWN_ABNORMAL_VALUES],
]


class WearClassificationTests(SimpleTestCase):
    def test_explicit_terms_and_unknowns(self):
        for value, expected in WEAR_CASES:
            with self.subTest(value=value):
                self.assertEqual(normalize_wear(value), expected)
                self.assertEqual(is_wear_recorded(value), expected is not None)

    def test_unknowns_do_not_inflate_rate_or_become_normal(self):
        values = ['无异常', '正常磨损', ' chip ', '其他', '', None]
        self.assertEqual(classify_wear_counts(values), {
            'normal': 2, 'abnormal': 1, 'unrecorded': 3, 'recorded': 3,
        })
        self.assertEqual(abnormal_rate(values), 33.3)
        self.assertIsNone(abnormal_rate(['其他', '', None]))

    def test_raw_unknown_text_remains_available_for_display(self):
        self.assertEqual(wear_display(' 人工纠正 '), '人工纠正')
        self.assertEqual(wear_display(' moderate '), '中度磨损')


class WearOrmContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        project = ProjectInfo.objects.create(project_id='WEAR-CONTRACT', project_name='Wear contract')
        machine = ShieldMachineBasicInfo.objects.create(shield_model_id='WEAR', shield_model='Wear')
        opening = WarehouseOpeningBasicInfo(
            warehouse_id='WEAR-100', project=project, shield_model=machine,
            ring_no='100', open_time=timezone.now(),
        )
        # Avoid opening/mobile workflow signals; these fixtures test read contracts.
        WarehouseOpeningBasicInfo.objects.bulk_create([opening])
        rows = [ToolChangeDetail(
            warehouse=opening, cutter_position_no=str(index + 1),
            tool_parent_type='DISC', wear_condition=value,
        ) for index, (value, _) in enumerate(WEAR_CASES)]
        ToolChangeDetail.objects.bulk_create(rows)
        cls.expected = {state: {row.pk for row, (_, expected) in zip(rows, WEAR_CASES)
                               if expected == state} for state in ('NORMAL', 'ABNORMAL', None)}

    def test_filter_and_aggregate_match_python_with_case_and_whitespace(self):
        query = ToolChangeDetail.objects.filter(warehouse__warehouse_id='WEAR-100')
        for condition, state in [(Q_WEAR_NORMAL, 'NORMAL'), (Q_WEAR_ABNORMAL, 'ABNORMAL')]:
            self.assertEqual(set(query.filter(condition).values_list('pk', flat=True)), self.expected[state])
        known_ids = self.expected['NORMAL'] | self.expected['ABNORMAL']
        self.assertEqual(set(query.filter(Q_WEAR_RECORDED).values_list('pk', flat=True)), known_ids)
        self.assertEqual(query.aggregate(
            normal=Count('pk', filter=Q_WEAR_NORMAL),
            abnormal=Count('pk', filter=Q_WEAR_ABNORMAL),
            recorded=Count('pk', filter=Q_WEAR_RECORDED),
        ), {'normal': len(self.expected['NORMAL']), 'abnormal': len(self.expected['ABNORMAL']),
            'recorded': len(known_ids)})

    def test_custom_field_expression_has_same_contract(self):
        query = ToolChangeDetail.objects.filter(warehouse__warehouse_id='WEAR-100').annotate(
            custom_wear=F('wear_condition'),
        )
        for factory, state in [(q_wear_normal, 'NORMAL'), (q_wear_abnormal, 'ABNORMAL')]:
            self.assertEqual(set(query.filter(factory('custom_wear')).values_list('pk', flat=True)), self.expected[state])
        self.assertEqual(query.filter(q_wear_recorded('custom_wear')).count(),
                         len(self.expected['NORMAL'] | self.expected['ABNORMAL']))
