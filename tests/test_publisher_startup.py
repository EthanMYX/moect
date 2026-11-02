import unittest
from core.publisher_startup import StartupGuard


class PublisherStartupTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.guard = StartupGuard(timeout=10, clock=lambda: self.now)

    def test_timeout_retries_once_and_then_stops(self):
        self.now = 9
        self.assertIsNone(self.guard.tick())
        self.now = 10
        self.assertEqual(self.guard.tick(), 'reload')
        self.now = 20
        self.assertEqual(self.guard.tick(), 'failed')
        for _ in range(10):
            self.assertIsNone(self.guard.tick())

    def test_late_previous_document_cannot_hide_the_startup_cover(self):
        generation = self.guard.generation
        self.guard.begin_document()
        self.assertFalse(self.guard.mark_ready(generation))
        self.assertFalse(self.guard.mark_ready(None))
        self.assertTrue(self.guard.mark_ready(self.guard.generation))
        self.now = 100
        self.assertIsNone(self.guard.tick())

    def test_renderer_failure_recovers_but_old_page_errors_are_ignored(self):
        self.guard.mark_ready(self.guard.generation)
        self.guard.fail('renderer_failed', generation=-1)
        self.assertTrue(self.guard.is_ready)
        self.guard.fail('renderer_failed')
        self.assertEqual(self.guard.tick(), 'reload')
        self.guard.mark_ready(self.guard.generation)
        self.assertTrue(self.guard.is_ready)

    def test_manual_retry_resets_the_bounded_budget(self):
        self.now = 10
        self.guard.tick()
        self.now = 20
        self.guard.tick()
        self.guard.manual_retry()
        self.assertFalse(self.guard.failed)
        self.assertEqual(self.guard.retries, 0)
        self.now = 30
        self.assertEqual(self.guard.tick(), 'reload')


if __name__ == '__main__':
    unittest.main()
