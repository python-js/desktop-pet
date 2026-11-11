"""Regeneration branches preserve source history, drafts, and task state."""
import os
import tempfile
import unittest
from desktop_pet.core import TaskStore


class RegenerationStoreTests(unittest.TestCase):
    def test_branch_keeps_only_context_before_latest_answer(self):
        store = TaskStore(':memory:')
        try:
            store.add_message('user', 'first')
            store.add_message('assistant', 'first reply')
            store.add_message('user', 'second')
            store.add_message('assistant', 'old second reply')
            store.add_message('assistant', 'saved task notice')
            store.save_input('default', 'unsent')
            store.save_draft('draft', '2099-01-01T12:00:00Z')
            before = store.messages()
            branch = store.branch_for_regeneration('default')
            self.assertEqual(store.messages(session_id=branch), before[:3])
            self.assertEqual(store.messages(), before)
            self.assertEqual(store.session('default')['input_text'], 'unsent')
            self.assertEqual(store.session(branch)['input_text'], '')
            self.assertEqual(store.drafts(branch), [])
            self.assertEqual(len(store.drafts('default')), 1)
            self.assertEqual(store.pending(), [])
        finally:
            store.close()

    def test_unanswered_latest_question_is_not_regeneratable(self):
        store = TaskStore(':memory:')
        try:
            for role, text in [('user', 'old'), ('assistant', 'reply'), ('user', 'unanswered')]:
                store.add_message(role, text)
            self.assertEqual(store.regeneration_context('default'), [])
            with self.assertRaises(ValueError):
                store.branch_for_regeneration('default')
            self.assertEqual(len(store.sessions()), 1)
        finally:
            store.close()

    def test_branch_context_bounded_and_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'test.db')
            store = TaskStore(path)
            for i in range(25):
                store.add_message('user', str(i))
                store.add_message('assistant', 'answer ' + str(i))
            branch = store.branch_for_regeneration('default')
            self.assertEqual(len(store.messages(session_id=branch)), 20)
            store.close()
            store = TaskStore(path)
            try:
                self.assertEqual(store.messages(session_id=branch)[-1]['content'], '24')
                self.assertEqual(store.messages()[-1]['content'], 'answer 24')
            finally:
                store.close()
