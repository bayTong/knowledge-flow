from importlib.metadata import version
from pathlib import Path
import unittest

import knowledgeflow_capture


class PackageSmokeTest(unittest.TestCase):
    def test_imports_editable_package_from_src_tree(self) -> None:
        repository_root = Path(__file__).resolve().parents[3]
        expected_module = (
            repository_root / "src" / "knowledgeflow_capture" / "__init__.py"
        ).resolve()

        self.assertEqual(Path(knowledgeflow_capture.__file__).resolve(), expected_module)
        self.assertEqual(
            version("knowledgeflow-capture"), knowledgeflow_capture.__version__
        )


if __name__ == "__main__":
    unittest.main()
