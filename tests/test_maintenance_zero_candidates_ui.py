import unittest
from manager.web_app import APP_JS
class Tests(unittest.TestCase):
 def test_zero_candidates_cannot_prepare_or_execute(self):
  s=APP_JS.decode();self.assertIn('lastPreview=p.candidate_count>0?',s);self.assertIn('Sin candidatos · Prepare y Execute deshabilitados',s);self.assertIn('prepareLogsButton.hidden=p.candidate_count===0',s)
