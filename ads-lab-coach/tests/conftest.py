import os
import tempfile

os.environ["ADS_COACH_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
