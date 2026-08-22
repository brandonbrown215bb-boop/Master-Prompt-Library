import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def test_project_metadata_identifies_a_dependency_free_package(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project = re.search(r"(?ms)^\[project\]\s*(.*?)(?=^\[|\Z)", pyproject)
        self.assertIsNotNone(project)
        project_text = project.group(1)

        for field, expected in {
            "name": "comfyui-master-prompt-library",
            "version": "2.1.0",
            "readme": "README.md",
            "requires-python": ">=3.10",
        }.items():
            self.assertRegex(project_text, rf'(?m)^{re.escape(field)}\s*=\s*"{re.escape(expected)}"\s*$')
        self.assertRegex(project_text, r'(?m)^license\s*=\s*\{\s*file\s*=\s*"LICENSE"\s*\}\s*$')
        self.assertRegex(project_text, r"(?m)^dependencies\s*=\s*\[\s*\]\s*$")

    def test_module_exports_package_version(self):
        module = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
        version = next(
            node.value.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        self.assertEqual(version, "2.1.0")

        exported = next(
            node.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        )
        self.assertIn("__version__", [item.value for item in exported.elts])

    def test_workflow_runs_python_and_node_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests -p 'test_*.py' -v", workflow)
        self.assertIn("node --test tests/*.mjs", workflow)


if __name__ == "__main__":
    unittest.main()
