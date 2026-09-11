import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from supervisor_engine import Model, Router, StateStore, classify_error, context_pack


class EngineTests(unittest.TestCase):
    def test_router_never_reuses_model(self):
        state = {"used_models": [], "unavailable_models": {}}
        models = [Model("a/x", "a", context=100), Model("b/y", "b", context=200)]
        router = Router(models, state)
        first = router.choose().id
        second = router.choose().id
        self.assertEqual({first, second}, {"a/x", "b/y"})
        with self.assertRaises(RuntimeError):
            router.choose()

    def test_router_filters_capabilities(self):
        state = {"used_models": [], "unavailable_models": {}}
        models = [Model("a/plain", "a", context=100), Model("b/tools", "b", context=200, toolcall=True)]
        self.assertEqual(Router(models, state).choose(needs_tools=True).id, "b/tools")

    def test_error_classification(self):
        self.assertEqual(classify_error("HTTP 429 rate limit"), "rate_limit")
        self.assertEqual(classify_error("context length exceeded"), "context_overflow")
        self.assertEqual(classify_error("provider unavailable 503"), "provider_outage")

    def test_context_pack_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp))
            state = store.load()
            state["tasks"]["task-1"] = {"title": "x", "prompt": "important", "status": "pending"}
            store.save(state)
            (Path(tmp) / "reports").mkdir()
            (Path(tmp) / "reports" / "old.md").write_text("x" * 1000, encoding="utf-8")
            result = context_pack(store, state, "task-1", 300)
            self.assertLessEqual(len(result), 300)
            self.assertIn("important", result)


if __name__ == "__main__":
    unittest.main()
