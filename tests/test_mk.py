import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("mk", pathlib.Path(__file__).parent.parent / "harness" / "mk.py")
mk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk)


class WithMention(unittest.TestCase):
    def test_local_user(self):
        self.assertEqual(mk.with_mention("hi", {"username": "alice", "host": None}, "bot"), "@alice hi")

    def test_remote_user(self):
        self.assertEqual(mk.with_mention("hi", {"username": "bob", "host": "example.net"}, "bot"), "@bob@example.net hi")

    def test_already_mentioned(self):
        self.assertEqual(mk.with_mention("@alice hi", {"username": "alice", "host": None}, "bot"), "@alice hi")

    def test_self_reply(self):
        self.assertEqual(mk.with_mention("hi", {"username": "bot", "host": None}, "bot"), "hi")

    def test_no_text(self):
        self.assertIsNone(mk.with_mention(None, {"username": "alice", "host": None}, "bot"))


class Token(unittest.TestCase):
    def test_missing_token_exits(self):
        env = mk.os.environ
        saved = {k: env.pop(k) for k in ("MISSKEY_MUGI_TOKEN", "MISSKEY_TOKEN") if k in env}
        try:
            with self.assertRaises(SystemExit):
                mk.token()
        finally:
            env.update(saved)


if __name__ == "__main__":
    unittest.main()
