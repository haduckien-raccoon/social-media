import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.test import override_settings


@override_settings(
    REDIS_URL="",
    CHANNEL_LAYERS={
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    },
)
class BenchmarkCommandTests(TestCase):
    def test_benchmark_command_outputs_json(self):
        output = StringIO()
        call_command(
            "benchmark_realtime_fanout",
            subscribers=[2],
            iterations=2,
            query_iterations=2,
            query_limit=10,
            as_json=True,
            stdout=output,
        )

        payload = json.loads(output.getvalue())
        self.assertIn("query", payload)
        self.assertIn("fanout", payload)
        self.assertEqual(payload["fanout"][0]["subscribers"], 2)
