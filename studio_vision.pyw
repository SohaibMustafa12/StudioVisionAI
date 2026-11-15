"""Studio Vision AI launcher.  Run:  python studio_vision.pyw   (or double-click it on Windows).
Self-test:  python studio_vision.pyw --selftest report.json [--quick]"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if "--selftest" in sys.argv:
    # sandbox: separate data folder + settings so a test run never touches your history or preferences
    os.environ["SV_DATA_DIR"] = tempfile.mkdtemp(prefix="sv_selftest_data_")

from sv.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
