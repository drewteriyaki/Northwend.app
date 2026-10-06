"""The conclusion policy's output check on Ask Northwend's streamed answers
(advisor.policed, ai_policy.check): each sentence is shown only once it
passes, and one that concludes for the person ends the answer calmly."""

import os
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import ai_policy  # noqa: E402


def _run(chunks, allowed=None):
    return "".join(advisor.policed(iter(chunks), allowed_tickers=allowed))


class PolicedTests(unittest.TestCase):

    def test_a_calm_explanation_streams_through_unchanged(self):
        chunks = ["A bond fund holds loans to companies ", "and governments. ",
                  "Its price moves less than a stock fund's, usually.\n",
                  "Want me to explain duration?"]
        self.assertEqual(_run(chunks), "".join(chunks))

    def test_a_conclusion_for_the_person_ends_the_answer(self):
        chunks = ["Bonds are loans. ", "You should move some of your money into bonds. ",
                  "Here is more text that must never show."]
        out = _run(chunks)
        self.assertIn("Bonds are loans.", out)
        self.assertIn(ai_policy.FALLBACK, out)
        self.assertNotIn("move some of your money", out)
        self.assertNotIn("must never show", out)

    def test_soft_forms_are_caught_too(self):
        out = _run(["Most people in your position would hold more bonds. "])
        self.assertIn(ai_policy.FALLBACK, out)

    def test_the_last_unfinished_sentence_is_checked(self):
        self.assertIn(ai_policy.FALLBACK, _run(["Fine so far. ", "I'd move half to bonds"]))
        self.assertEqual(_run(["Fine so far. ", "That's the idea"]), "Fine so far. That's the idea")

    def test_the_stream_stops_being_read_after_a_break(self):
        read = []

        def gen():
            for c in ["You should buy bonds now. ", "never read"]:
                read.append(c)
                yield c
        out = "".join(advisor.policed(gen()))
        self.assertIn(ai_policy.FALLBACK, out)
        self.assertEqual(read, ["You should buy bonds now. "])

    def test_the_rules_are_in_the_shared_prompt_block(self):
        self.assertIn(ai_policy.rules_text(), advisor.chat_rules())

    def test_the_chat_page_wraps_the_stream(self):
        with open(os.path.join(REPO, "views", "assistant.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("advisor.policed(advisor.stream_reply(", src)


if __name__ == "__main__":
    unittest.main()
