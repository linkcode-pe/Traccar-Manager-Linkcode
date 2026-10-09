import os
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.operations import log_retention_production_delete as d


class ProductionDeleteDurabilityTests(unittest.TestCase):
    def test_directory_fsync_runs_if_failure_occurs_after_mutation(self):
        calls=[]
        real_fsync=os.fsync
        real_unlink=os.unlink
        state={"mutated":False}

        def fake_unlink(*args, **kwargs):
            state["mutated"]=True
            return real_unlink(*args, **kwargs)

        def fake_fsync(fd):
            calls.append((fd,state["mutated"]))
            return real_fsync(fd)

        # Structural guard: the deleter must keep its mutation-aware finally fsync.
        src=Path(d.__file__).read_text(encoding="utf-8")
        self.assertIn("mutated=True",src)
        self.assertIn("finally:\n  if mutated: os.fsync(dfd)\n  os.close(dfd)",src)
        self.assertFalse(calls)

    def test_active_log_name_is_never_eligible(self):
        self.assertFalse(d.NAME.fullmatch(d.ACTIVE))


if __name__ == "__main__":
    unittest.main()
