"""刀具里程推算与寿命与厂家接口。"""
import math

from django.test import SimpleTestCase, TestCase

from .mileage import (
    REFERENCE_PENETRATION_MM, RING_WIDTH_MM, RingRevolutions, group_by_trajectory,
    kilometres, manufacturer_cells, spread,
)
from .models import OldToolRecord, ShieldTunnelingData
# 只引用模块：把测试类导入本模块会让测试运行器再跑一遍它的用例
from . import test_analysis
from .trajectory import get_tool_trajectory

REFERENCE = RING_WIDTH_MM / REFERENCE_PENETRATION_MM


def segment(manufacturer='A', km=100.0, radius=3000, position='30', tool_type='DISC', **fields):
    return {'manufacturer': manufacturer, 'km': km, 'radius_mm': radius, 'cutter_position_no': position,
            'tool_parent_type': tool_type, 'wear_state': 'NORMAL', 'wear_per_100km': 1.0, 'price': 100.0, **fields}


class MileageCalculationTests(SimpleTestCase):
    def test_tunneling_rings_use_weighted_penetration_and_the_rest_the_reference(self):
        revolutions = RingRevolutions([(1, 1, '5', 20, 30), (1, 1, '5', 10, 10), (1, 1, '6', None, 5), (1, 1, 'X', 10, 1)])
        self.assertAlmostEqual(revolutions.measured[(1, 1, 5)], RING_WIDTH_MM / 17.5)
        total, estimated = revolutions.span(1, 1, 4, 6)
        self.assertAlmostEqual(total, RING_WIDTH_MM / 17.5 + REFERENCE)
        self.assertAlmostEqual(estimated, REFERENCE)
        self.assertEqual(revolutions.span(1, 2, 4, 6), (2 * REFERENCE, 2 * REFERENCE))
        self.assertEqual(revolutions.span(1, 1, 6, 6), (0.0, 0.0))

    def test_kilometres_are_the_circumference_of_the_trajectory_times_revolutions(self):
        self.assertAlmostEqual(kilometres(1000, 120), 2 * math.pi * 120 / 1000)

    def test_fewer_than_five_values_are_listed_otherwise_median_and_quartiles(self):
        self.assertIsNone(spread([]))
        self.assertEqual(spread([3, 1.234]), {'count': 2, 'values': [1.23, 3]})
        self.assertEqual(spread([1, 2, 3, 4, 5]), {'count': 5, 'median': 3, 'q1': 2, 'q3': 4})

    def test_cells_count_wear_classes_and_give_cost_intensity_only_from_five_priced_segments(self):
        rows = [segment(km=50, price=100, wear_state=state) for state in ('NORMAL', 'ABNORMAL', 'ABNORMAL', None)]
        [cell] = manufacturer_cells(rows, [segment(km=12, in_service=True)])
        self.assertEqual((cell['removed_count'], cell['abnormal_count'], cell['classified_count'], cell['unclassified_count']), (4, 2, 3, 1))
        self.assertIsNone(cell['cost_per_km'])
        self.assertEqual((cell['in_service_count'], cell['in_service_km']), (1, {'count': 1, 'values': [12]}))
        [cell] = manufacturer_cells(rows + [segment(km=50, price=None), segment(km=50, price=150)], [])
        self.assertEqual((cell['priced_count'], cell['cost_per_km']), (5, round(550 / 250, 2)))

    def test_positions_on_one_radius_share_a_trajectory_inside_a_1000_mm_band(self):
        rows = [segment(position='78', radius=6770.8), segment(position='Y3', radius=6770.8, manufacturer='B'),
                segment(position='79', radius=6809.8), segment(position='S1L', radius=3430, tool_type='SCRAPER')]
        disc, scraper = group_by_trajectory(rows, [])
        [band] = disc['bands']
        self.assertEqual((band['radius_min'], band['radius_max'], band['trajectory_count']), (6000, 7000, 2))
        self.assertEqual(band['trajectories'][0]['positions'], ['78', 'Y3'])
        self.assertEqual([cell['manufacturer'] for cell in band['trajectories'][0]['cells']], ['A', 'B'])
        self.assertEqual(band['trajectories'][0]['summary']['removed_count'], 2)
        self.assertEqual((disc['manufacturers'], disc['summary']['removed_count'], band['summary']['removed_count']), (['A', 'B'], 3, 3))
        self.assertEqual((scraper['label'], scraper['bands'][0]['radius_min']), ('刮刀', 3000))


class LifeMileageApiTests(TestCase):
    """沿用分析接口测试的项目、开仓和换刀明细构造。"""
    setUpTestData = classmethod(test_analysis.AnalysisContractTests.setUpTestData.__func__)
    opening = test_analysis.AnalysisContractTests.opening
    detail = test_analysis.AnalysisContractTests.detail
    query = test_analysis.AnalysisContractTests.query
    install = test_analysis.AnalysisContractTests.install

    def pair(self, install_ring, remove_ring, position='1', removed_position=None, manufacturer='A', **removal):
        installed = self.detail(self.opening(install_ring), position, is_replaced=True, price=200, manufacturer=manufacturer)
        instance = self.install(installed)
        removed = self.detail(self.opening(remove_ring), removed_position or position, is_replaced=True, **removal)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=instance, inspection_status='CONFIRMED')
        return installed, removed

    def test_removed_segment_mileage_wear_rate_and_the_tool_still_in_service(self):
        ShieldTunnelingData.objects.create(project=self.project, shield_machine=self.machine, ring_no='150',
                                           penetration=20, point_count=10)
        self.pair(100, 200, wear_condition='偏磨', blade_wear_amount=10, manufacturer='B')
        self.detail(self.opening(300), '2', is_replaced=True, manufacturer='C')
        data = self.query('life_mileage')
        radius = get_tool_trajectory('1', 'DISC')['radius_mm']
        revolutions = 99 * REFERENCE + RING_WIDTH_MM / 20
        [row] = data['segments']
        self.assertEqual((row['manufacturer'], row['radius_mm'], row['service_rings']), ('B', radius, 100))
        self.assertEqual(row['km'], round(kilometres(radius, revolutions), 2))
        self.assertEqual(row['estimated_share'], round(99 * REFERENCE / revolutions, 3))
        self.assertEqual((row['wear_state'], row['wear_per_100km']), ('ABNORMAL', round(10 / kilometres(radius, revolutions) * 100, 3)))
        self.assertEqual(row['price'], 200)
        # 第 200 环换下的同时装上新刀，到范围内最后一次开仓（第 300 环）一直在役
        service = {item['cutter_position_no']: item for item in data['in_service']}
        self.assertEqual((service['1']['installation_ring_no'], service['1']['through_ring_no']), ('200', '300'))
        self.assertEqual(service['1']['km'], round(kilometres(radius, 100 * REFERENCE), 2))
        self.assertEqual(service['2']['km'], 0)
        [position] = [item for item in data['positions'] if item['cutter_position_no'] == '1']
        self.assertEqual(position['covered_km'], round(row['km'] + service['1']['km'], 2))
        self.assertEqual(data['revolution_basis']['tunneling_ring_count'], 1)
        self.assertEqual(data['meta']['schema_version'], 2)

    def test_lowercase_positions_are_reported_in_their_canonical_form(self):
        self.pair(100, 200, position='y3')
        data = self.query('life_mileage')
        self.assertEqual([row['cutter_position_no'] for row in data['segments']], ['Y3'])
        self.assertEqual([row['cutter_position_no'] for row in data['positions']], ['Y3'])
        self.assertEqual(data['groups'][0]['bands'][0]['trajectories'][0]['positions'], ['Y3'])

    def test_mismatched_positions_and_unconfirmed_pairs_are_excluded_with_a_reason(self):
        _, mismatched = self.pair(100, 200, position='1', removed_position='2')
        installed = self.detail(self.opening(100), '3', is_replaced=True, manufacturer='A')
        removed = self.detail(self.opening(200), '3', is_replaced=True)
        OldToolRecord.objects.create(tool_change_detail=removed, confirmed_tool_instance=self.install(installed))
        data = self.query('life_mileage')
        self.assertEqual(data['segments'], [])
        reasons = {item['reason']: item['count'] for item in data['excluded']}
        self.assertEqual((reasons['安装与拆除不在同一刀位'], reasons['厂家反馈未确认']), (1, 1))
        self.assertEqual(len(data['excluded_rows']), sum(reasons.values()))
        [row] = [row for row in data['excluded_rows'] if row['reason'] == '安装与拆除不在同一刀位']
        self.assertEqual((row['cutter_position_no'], row['ring_no'], row['opening_id']), ('2', '200', mismatched.warehouse_id))

    def test_ring_scope_follows_removal_and_manufacturer_filter_applies_to_both_lists(self):
        self.pair(100, 200, manufacturer='A')
        self.pair(200, 300, position='4', manufacturer='B')
        self.detail(self.opening(300), '5', is_replaced=True, manufacturer='A')
        self.detail(self.opening(300), '6', is_replaced=True, manufacturer='B')
        scoped = self.query('life_mileage', start_ring=250)
        self.assertEqual([row['manufacturer'] for row in scoped['segments']], ['B'])
        only_a = self.query('life_mileage', manufacturer='A')
        self.assertEqual([row['manufacturer'] for row in only_a['segments']], ['A'])
        self.assertEqual([row['cutter_position_no'] for row in only_a['in_service']], ['5'])
        groups = only_a['groups'][0]['bands'][0]['cells']
        self.assertEqual([cell['manufacturer'] for cell in groups], ['A'])
