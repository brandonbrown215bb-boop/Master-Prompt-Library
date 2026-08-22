import json
import inspect
import tempfile
import unittest
import uuid
from pathlib import Path

from library_store import CATEGORIES, LibraryStore
from prompt_library_node import MasterPromptLibrary, set_library_store


def document():
    categories = {category: [] for category in CATEGORIES}
    for category, name, prompt in (
        ("style", "Painterly", "visible brushwork"),
        ("character", "Pilot", "a seasoned pilot"),
        ("action", "Running", "running through rain"),
        ("background", "Harbor", "a stormy harbor"),
    ):
        categories[category].append({"id": str(uuid.uuid4()), "name": name, "prompt": prompt, "image": None})
    return {"version": 1, "categories": categories}


class PromptLibraryNodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        seed = root / "seed.json"
        seed.write_text(json.dumps(document()), encoding="utf-8")
        self.store = LibraryStore(root / "user", seed_path=seed)
        set_library_store(self.store)

    def tearDown(self):
        set_library_store(None)
        self.tmp.cleanup()

    def test_dynamic_inputs_and_default_assembly(self):
        inputs = MasterPromptLibrary.INPUT_TYPES()["required"]
        self.assertEqual(inputs["style"][0][0], "✨ none")
        result = MasterPromptLibrary.assemble(
            "a red flag",
            "Painterly",
            "Pilot",
            "Running",
            "Harbor",
            "style, character, action, background, prompt",
        )
        self.assertEqual(result[0], "Style: visible brushwork\n\nCharacter: a seasoned pilot\n\nAction: running through rain\n\nBackground: a stormy harbor\n\nPrompt: a red flag")
        self.assertEqual(result[1:5], ("visible brushwork", "a seasoned pilot", "running through rain", "a stormy harbor"))
        self.assertEqual(json.loads(result[5])["style"], "Painterly")

    def test_order_ignores_unknown_duplicates_and_appends_omissions(self):
        result = MasterPromptLibrary.assemble(
            "prompt", "Painterly", "Pilot", "Running", "Harbor", "prompt,style,style,wat"
        )
        self.assertEqual(result[0], "Prompt: prompt\n\nStyle: visible brushwork\n\nCharacter: a seasoned pilot\n\nAction: running through rain\n\nBackground: a stormy harbor")

    def test_stale_and_none_selections_are_empty_but_valid(self):
        result = MasterPromptLibrary.assemble("prompt", "deleted", "✨ none", "deleted", "Harbor")
        self.assertEqual(result[0], "Background: a stormy harbor\n\nPrompt: prompt")
        summary = json.loads(result[5])
        self.assertIsNone(summary["style"])
        self.assertIsNone(summary["character"])
        self.assertIsNone(summary["action"])
        self.assertEqual(summary["background"], "Harbor")
        self.assertTrue(MasterPromptLibrary.VALIDATE_INPUTS(style="deleted", character="✨ none"))

    def test_validation_signature_only_overrides_combo_membership(self):
        signature = inspect.signature(MasterPromptLibrary.VALIDATE_INPUTS)
        self.assertNotIn(inspect.Parameter.VAR_KEYWORD, [parameter.kind for parameter in signature.parameters.values()])
        self.assertEqual(
            list(signature.parameters),
            ["style", "character", "action", "background"],
        )

    def test_library_fingerprint_changes(self):
        before = MasterPromptLibrary.IS_CHANGED()
        self.store.create_entry("style", "New", "new prompt")
        self.assertNotEqual(before, MasterPromptLibrary.IS_CHANGED())


if __name__ == "__main__":
    unittest.main()
