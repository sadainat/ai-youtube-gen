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