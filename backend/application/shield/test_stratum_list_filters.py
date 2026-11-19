from django.test import TestCase
from rest_framework.test import APIClient

from dvadmin.system.models import Users
from application.shield.models import ProjectInfo, StratumBasicInfo


class StratumListRingRangeTests(TestCase):
    """地层列表按环号范围查询：ring_no 是字符串，范围必须按数值比较。"""

    def setUp(self):
        user = Users.objects.create(username="stratum-filter", name="地层查询", is_active=True, is_staff=True, is_superuser=True)
        self.client = APIClient()
        self.client.force_authenticate(user=user)
        self.project = ProjectInfo.objects.create(project_id="STRATUM-FILTER", project_name="地层查询项目")
        other = ProjectInfo.objects.create(project_id="STRATUM-OTHER", project_name="其他项目")
        for ring in ("2", "9", "10", "99", "100", "250"):
            StratumBasicInfo.objects.create(project=self.project, ring_no=ring)
        StratumBasicInfo.objects.create(project=other, ring_no="50")

    def rings(self, **params):
        response = self.client.get("/api/shield/stratum_basic_info/", {"limit": 100, **params})
        self.assertEqual(response.data["code"], 2000)
        return [row["ring_no"] for row in response.data["data"]]

    def test_range_is_numeric_and_inclusive(self):
        self.assertEqual(self.rings(project=self.project.id, ring_start="9", ring_end="100"), ["9", "10", "99", "100"])

    def test_one_sided_and_project_filters(self):
        self.assertEqual(self.rings(project=self.project.id, ring_start="100"), ["100", "250"])
        self.assertEqual(self.rings(ring_end="9"), ["2", "9"])
        self.assertEqual(self.rings(ring_start="40", ring_end="60"), ["50"])

    def test_blank_or_non_numeric_bounds_are_ignored(self):
        self.assertEqual(len(self.rings(ring_start="", ring_end="abc")), 7)
