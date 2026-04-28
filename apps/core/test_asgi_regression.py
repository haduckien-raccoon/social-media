import subprocess
import sys

from django.test import SimpleTestCase


class ASGIRegressionTests(SimpleTestCase):
	def test_asgi_imports_from_clean_python_process(self):
		result = subprocess.run(
			[
				sys.executable,
				"-c",
				"import config.asgi; print(config.asgi.application.__class__.__name__)",
			],
			capture_output=True,
			text=True,
			check=False,
		)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("ProtocolTypeRouter", result.stdout)
