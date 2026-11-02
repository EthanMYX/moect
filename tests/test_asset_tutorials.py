"""Durable, independent first-visit tutorial preferences; synthetic state only."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.service import Service
from tests.test_resources import ASSETS


class AssetTutorialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.service=Service(ASSETS,self.root)
        self.addCleanup(self.service.shutdown)

    def test_status_does_not_consume_first_visit_before_tutorial_is_displayed(self):
        for kind in ('moments','stickers'):
            for _ in range(2):self.assertEqual(self.service.call('tutorial_status',{'kind':kind}),{'seen':False})
        self.assertFalse(self.service.config_path.exists())

    def test_seen_flags_are_independent_and_survive_restart(self):
        self.service.call('tutorial_seen',{'kind':'moments'})
        self.assertTrue(self.service.call('tutorial_status',{'kind':'moments'})['seen'])
        self.assertFalse(self.service.call('tutorial_status',{'kind':'stickers'})['seen'])
        reloaded=Service(ASSETS,self.root)
        try:
            self.assertTrue(reloaded.call('tutorial_status',{'kind':'moments'})['seen'])
            self.assertFalse(reloaded.call('tutorial_status',{'kind':'stickers'})['seen'])
        finally:reloaded.shutdown()

    def test_replay_acknowledgement_is_idempotent_and_does_not_reset_other_preferences(self):
        self.service.settings({'accent':'rose','theme':'dark'})
        with patch.object(self.service,'save',wraps=self.service.save) as save:
            self.service.call('tutorial_seen',{'kind':'stickers'})
            self.service.call('tutorial_seen',{'kind':'stickers'})
            self.assertEqual(save.call_count,1)
        self.assertEqual(self.service.config['accent'],'rose');self.assertEqual(self.service.config['theme'],'dark')

    def test_demo_and_logout_do_not_reset_seen_tutorials(self):
        self.service.call('tutorial_seen',{'kind':'moments'})
        self.service.demo();self.service.logout()
        self.assertTrue(self.service.call('tutorial_status',{'kind':'moments'})['seen'])

    def test_invalid_tutorial_and_failed_save_do_not_mark_as_seen(self):
        for kind in (None,'other',[],{}):
            with self.assertRaises(ValueError):self.service.call('tutorial_seen',{'kind':kind})
        with patch.object(self.service,'save',side_effect=OSError('synthetic read-only state')):
            with self.assertRaises(ValueError):self.service.call('tutorial_seen',{'kind':'moments'})
        self.assertFalse(self.service.call('tutorial_status',{'kind':'moments'})['seen'])

    def test_malformed_saved_flags_recover_without_assuming_truthy_values_are_seen(self):
        state=self.root/'separate';state.mkdir()
        (state/'config.json').write_text(json.dumps({'asset_tutorials':{'moments':'false','stickers':True}}))
        reloaded=Service(ASSETS,state)
        try:
            self.assertFalse(reloaded.call('tutorial_status',{'kind':'moments'})['seen'])
            self.assertTrue(reloaded.call('tutorial_status',{'kind':'stickers'})['seen'])
        finally:reloaded.shutdown()


if __name__=='__main__':unittest.main()
