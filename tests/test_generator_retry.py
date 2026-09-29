from types import SimpleNamespace
import unittest
from unittest.mock import patch

from google.genai.errors import APIError

from src import generator


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TestGeneratorRetry(unittest.TestCase):
    def test_generate_json_retries_temporary_server_errors(self):
        models = FakeModels(
            [
                APIError(503, {"error": {"message": "busy"}}),
                APIError(503, {"error": {"message": "still busy"}}),
                SimpleNamespace(text='{"ok": true}'),
            ]
        )
        delays = []
        with patch.object(
            generator,
            "_model",
            return_value=SimpleNamespace(models=models),
        ), patch.object(generator.time, "sleep", side_effect=delays.append):
            result = generator._generate_json("prompt")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(models.calls, 3)
        self.assertEqual(delays, [5, 10])

    def test_generate_json_does_not_retry_client_errors(self):
        models = FakeModels([APIError(400, {"error": {"message": "bad request"}})])
        delays = []
        with patch.object(
            generator,
            "_model",
            return_value=SimpleNamespace(models=models),
        ), patch.object(generator.time, "sleep", side_effect=delays.append):
            with self.assertRaises(APIError) as error:
                generator._generate_json("prompt")

        self.assertEqual(error.exception.code, 400)
        self.assertEqual(models.calls, 1)
        self.assertEqual(delays, [])

    def test_generate_json_uses_fallback_after_primary_server_errors(self):
        primary = FakeModels([APIError(503, {"error": {"message": "busy"}})] * 4)
        fallback = FakeModels([SimpleNamespace(text='{"ok": true}')])
        delays = []
        requested_models = []

        def generate_content(model, **kwargs):
            requested_models.append(model)
            target = primary if model == "gemini-3.6-flash" else fallback
            return target.generate_content(**kwargs)

        with patch.object(
            generator,
            "_model",
            side_effect=lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
        ), patch.object(generator, "MODEL_NAME", "gemini-3.6-flash"), patch.object(
            generator, "FALLBACK_MODEL_NAMES", ("gemini-3.8-flash", "gemini-3.5-flash")
        ), patch.object(generator.time, "sleep", side_effect=delays.append):
            result = generator._generate_json("prompt")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(requested_models, ["gemini-3.6-flash"] * 4 + ["gemini-3.8-flash"])
        self.assertEqual(delays, [5, 10, 20])

    def test_generate_json_tries_next_fallback_after_another_model_is_unavailable(self):
        primary = FakeModels([APIError(503, {"error": {"message": "busy"}})] * 4)
        first_fallback = FakeModels([APIError(503, {"error": {"message": "busy"}})] * 4)
        requested_models = []

        def generate_content(model, **kwargs):
            requested_models.append(model)
            if model == "gemini-3.6-flash":
                return primary.generate_content(**kwargs)
            if model == "gemini-3.8-flash":
                return first_fallback.generate_content(**kwargs)
            return SimpleNamespace(text='{"ok": true}')

        with patch.object(
            generator,
            "_model",
            return_value=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
        ), patch.object(generator, "MODEL_NAME", "gemini-3.6-flash"), patch.object(
            generator, "FALLBACK_MODEL_NAMES", ("gemini-3.8-flash", "gemini-3.5-flash")
        ), patch.object(generator.time, "sleep"):
            result = generator._generate_json("prompt")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            requested_models,
            ["gemini-3.6-flash"] * 4 + ["gemini-3.8-flash"] * 4 + ["gemini-3.5-flash"],
        )