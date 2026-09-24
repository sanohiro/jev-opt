#!/usr/bin/env python3
"""Unit tests for JevClient's endpoint routing and retry policy (decision
111), with a stubbed HTTP layer.

No network, no build, no timing: `JevClient._post` is replaced by a canned
queue of (status, headers, body) tuples and `_sleep` is a no-op recorder, so
a run of this file takes a fraction of a second. Run:

    python3 scripts/test_jev_client.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_search as S          # noqa: E402


def base_cfg():
    return dict(S.DEFAULTS["jev"])


class StubClient(S.JevClient):
    """A JevClient whose `_post` returns a scripted sequence of attempts
    instead of making an HTTP request. Each queue entry is
    (status, headers, body_dict_or_None); a body of None means "not valid
    JSON". Raises IndexError (surfaced as a test failure) if `ask()` asks
    for more attempts than were scripted."""

    def __init__(self, queue, *a, **kw):
        self._queue = list(queue)
        self.posts = []
        super().__init__(*a, **kw)
        self._sleep = lambda s: self._sleeps.append(s)
        self._sleeps = []

    def _post(self, payload, timeout):
        self.posts.append(json.loads(payload.decode()))
        status, headers, body = self._queue.pop(0)
        raw = b"" if body is None else json.dumps(body).encode()
        return status, headers, raw


def landed_body(model):
    return {"model": model,
            "answers": {"smoke": {"choice": "KEEP_DEFAULT",
                                  "probabilities": {"KEEP_DEFAULT": 1.0},
                                  "confidence": 1.0}},
            "usage": {"input_tokens": 10, "output_tokens": 1}}


def ask_smoke(client, round_no=1, phase="A"):
    return client.ask("state", {"smoke": {"type": "choice",
                                          "instructions": "x",
                                          "criteria": {"KEEP_DEFAULT": "x"}}},
                      round_no, phase, {})


class EndpointRouting(unittest.TestCase):
    """gateway and direct build the right URL, model and key env var."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "gw-secret",
                                                 "TYPESAFE_API_KEY": "ts-secret"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_gateway_is_the_default_url_and_model(self):
        c = StubClient([(200, {}, landed_body("typesafe-ai/jev"))],
                       base_cfg(), self.tmp, "r1")
        self.assertEqual(c.endpoint, "gateway")
        self.assertEqual(c.url, "https://ai-gateway.vercel.sh/typesafe"
                                "/v1/systemone")
        self.assertEqual(c.model, "typesafe-ai/jev")
        self.assertEqual(c.key_env, "AI_GATEWAY_API_KEY")
        ask_smoke(c)
        self.assertEqual(c.key, "gw-secret")
        req = c.posts[0]
        self.assertEqual(req["model"], "typesafe-ai/jev")

    def test_direct_url_headers_and_mapped_model(self):
        c = StubClient([(200, {}, landed_body("jev-latest"))],
                       base_cfg(), self.tmp, "r2", cli_endpoint="direct")
        self.assertEqual(c.endpoint, "direct")
        self.assertEqual(c.url, "https://api.typesafe.ai/v1/systemone")
        # docs.typesafe.ai: the direct API does not know the gateway's
        # namespaced id; the client maps it to the SDK's own default.
        self.assertEqual(c.model, "jev-latest")
        self.assertEqual(c.key_env, "TYPESAFE_API_KEY")
        ask_smoke(c)
        self.assertEqual(c.key, "ts-secret")
        self.assertEqual(c.posts[0]["model"], "jev-latest")

    def test_authorization_header_uses_the_resolved_key(self):
        c = StubClient([(200, {}, landed_body("jev-latest"))],
                       base_cfg(), self.tmp, "r3", cli_endpoint="direct")
        c.key = "ts-secret"
        seen = {}
        real_request = S.urllib.request.Request

        def spy_request(url, **kw):
            seen["url"] = url
            seen["headers"] = kw.get("headers")
            return real_request(url, **kw)

        def no_network(*a, **kw):
            raise RuntimeError("test: urlopen must not be called")
        # StubClient overrides `_post`; call the real implementation it is
        # stubbing, with `urlopen` itself blocked, so this checks what an
        # actual HTTP attempt would send without ever reaching the network.
        with mock.patch.object(S.urllib.request, "Request", spy_request), \
             mock.patch.object(S.urllib.request, "urlopen", no_network):
            try:
                S.JevClient._post(c, b"{}", 1.0)
            except Exception:
                pass
        self.assertEqual(seen["url"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(seen["headers"]["Authorization"],
                         "Bearer ts-secret")


class Precedence(unittest.TestCase):
    """cli > JEV_ENDPOINT (env/.env) > [jev] endpoint (toml) > auto."""

    def test_cli_beats_everything(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {"JEV_ENDPOINT": "direct",
                                          "TYPESAFE_API_KEY": "t"},
                             clear=True):
            cfg = base_cfg()
            cfg["endpoint"] = "direct"
            ep, src, key_env, base_url, err = S.resolve_endpoint(
                cfg, cli_endpoint="gateway")
        self.assertEqual((ep, src), ("gateway", "cli"))

    def test_env_beats_toml(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {"JEV_ENDPOINT": "direct",
                                          "TYPESAFE_API_KEY": "t"},
                             clear=True):
            cfg = base_cfg()
            cfg["endpoint"] = "gateway"
            ep, src, _, _, err = S.resolve_endpoint(cfg)
        self.assertEqual((ep, src), ("direct", "env"))
        self.assertIsNone(err)

    def test_toml_beats_auto(self):
        with mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "g",
                                          "TYPESAFE_API_KEY": "t"}, clear=True):
            cfg = base_cfg()
            cfg["endpoint"] = "direct"
            ep, src, _, _, err = S.resolve_endpoint(cfg)
        self.assertEqual((ep, src), ("direct", "toml"))


class AutoSelect(unittest.TestCase):
    """Nothing set explicitly: pick by which single API key is present."""

    def test_only_typesafe_key_selects_direct(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "t"},
                             clear=True):
            ep, src, key_env, _, err = S.resolve_endpoint(base_cfg())
        self.assertEqual((ep, src, key_env), ("direct", "auto",
                                              "TYPESAFE_API_KEY"))
        self.assertIsNone(err)

    def test_only_gateway_key_selects_gateway(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "g"},
                             clear=True):
            ep, src, key_env, _, err = S.resolve_endpoint(base_cfg())
        self.assertEqual((ep, src, key_env), ("gateway", "auto",
                                              "AI_GATEWAY_API_KEY"))

    def test_both_keys_present_keeps_the_default_route(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "g",
                                          "TYPESAFE_API_KEY": "t"},
                             clear=True):
            ep, src, _, _, err = S.resolve_endpoint(base_cfg())
        self.assertEqual(ep, "gateway")
        self.assertIsNone(err)

    def test_empty_env_line_counts_as_absent(self):
        """`AI_GATEWAY_API_KEY=` with nothing after the `=` (what copying
        .env.example and filling in only one key leaves behind) must not
        count as "present": auto-select has to skip it, not route to
        gateway and then have read_api_key immediately refuse it."""
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, ".env"), "w") as f:
            f.write("AI_GATEWAY_API_KEY=\nTYPESAFE_API_KEY=t\n")
        with mock.patch.object(S, "REPO", tmp), \
             mock.patch.dict(os.environ, {}, clear=True):
            ep, src, key_env, _, err = S.resolve_endpoint(base_cfg())
        self.assertEqual((ep, src, key_env), ("direct", "auto",
                                              "TYPESAFE_API_KEY"))
        self.assertIsNone(err)

    def test_neither_key_is_an_error_naming_both_variables(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {}, clear=True):
            ep, src, key_env, base_url, err = S.resolve_endpoint(base_cfg())
        self.assertIsNone(ep)
        self.assertIn("AI_GATEWAY_API_KEY", err)
        self.assertIn("TYPESAFE_API_KEY", err)

    def test_construction_never_raises_when_unresolved(self):
        """--dry-run / --print-state build a JevClient and must not need a
        key; the error surfaces only on the first ask()."""
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {}, clear=True):
            tmp = tempfile.mkdtemp()
            c = S.JevClient(base_cfg(), tmp, "r-unresolved")
            self.assertIsNotNone(c._endpoint_error)
            self.assertIsNone(c.url)
            with self.assertRaises(SystemExit):
                ask_smoke(c)

    def test_explicit_endpoint_with_missing_key_names_that_variable(self):
        with mock.patch.object(S, "REPO", "/nonexistent-for-test"), \
             mock.patch.dict(os.environ, {}, clear=True):
            tmp = tempfile.mkdtemp()
            c = S.JevClient(base_cfg(), tmp, "r-missing-key",
                            cli_endpoint="direct")
            self.assertIsNone(c._endpoint_error)   # route itself resolved
            with self.assertRaises(SystemExit) as ctx:
                ask_smoke(c)
            self.assertIn("TYPESAFE_API_KEY", str(ctx.exception))


class Retries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ,
                                   {"AI_GATEWAY_API_KEY": "gw-secret"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_529_is_retried_and_eventually_lands(self):
        cfg = base_cfg()
        c = StubClient([(529, {}, None),
                        (529, {}, None),
                        (200, {}, landed_body("typesafe-ai/jev"))],
                       cfg, self.tmp, "r4")
        answers, _ = ask_smoke(c)
        self.assertIsNotNone(answers)
        self.assertEqual(len(c.posts), 3)
        self.assertEqual(len(c._sleeps), 2)

    def test_529_honours_retry_after(self):
        cfg = base_cfg()
        c = StubClient([(529, {"Retry-After": "9"}, None),
                        (200, {}, landed_body("typesafe-ai/jev"))],
                       cfg, self.tmp, "r5")
        ask_smoke(c)
        self.assertGreaterEqual(c._sleeps[0], 9.0)

    def test_401_is_not_retried(self):
        cfg = base_cfg()
        c = StubClient([(401, {}, {"error": "bad key"}),
                        (200, {}, landed_body("typesafe-ai/jev"))],
                       cfg, self.tmp, "r6")
        answers, _ = ask_smoke(c)
        self.assertIsNone(answers)
        self.assertEqual(len(c.posts), 1)     # never reached the 2nd entry


class KeyNeverLogged(unittest.TestCase):
    def test_key_does_not_appear_in_either_log_file(self):
        tmp = tempfile.mkdtemp()
        secret = "sk-TOTALLY-SECRET-VALUE"
        with mock.patch.dict(os.environ, {"AI_GATEWAY_API_KEY": secret}):
            cfg = base_cfg()
            c = StubClient([(529, {"Retry-After": "0.01"}, None),
                            (200, {}, landed_body("typesafe-ai/jev"))],
                           cfg, tmp, "r7")
            ask_smoke(c)
        with open(c.jsonl_path) as f:
            jsonl = f.read()
        with open(c.log_path) as f:
            log = f.read()
        self.assertNotIn(secret, jsonl)
        self.assertNotIn(secret, log)
        # the key's env var NAME is fine to log; only the value is not
        self.assertIn("AI_GATEWAY_API_KEY", log)


if __name__ == "__main__":
    unittest.main()
