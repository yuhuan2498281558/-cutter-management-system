from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, override_settings

from application import settings as application_settings
from application import settings_ci


class CIMigrationConfigurationTests(SimpleTestCase):
    def test_only_shield_uses_test_syncdb_and_production_database_is_unchanged(self):
        self.assertEqual(settings_ci.MIGRATION_MODULES, {"shield": None})
        self.assertIsNot(settings_ci.DATABASES, application_settings.DATABASES)
        self.assertEqual(settings_ci.DATABASES["default"]["TEST"]["NAME"], "test_ai_ci")

    @override_settings(MIGRATION_MODULES={"shield": None})
    def test_system_and_memory_migrations_remain_in_graph(self):
        loader = MigrationLoader(None)
        self.assertIn("shield", loader.unmigrated_apps)
        self.assertIn(("system", "0001_initial"), loader.graph.nodes)
        self.assertEqual(loader.graph.leaf_nodes("ai_assistant"), [
            ("ai_assistant", "0002_assistantmemoryscope_generation"),
        ])
