"""Launch the web UI.

    python run_web.py

Inserts src/ into sys.path before uvicorn imports the app so the package
is always found regardless of whether the editable install .pth file was
processed by the Python launcher (an intermittent issue on Python 3.13).
The reload_dirs restriction prevents the .venv/ churn loop.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "candidate_transformer.ui:app",
        reload=True,
        reload_dirs=["src"],
        port=8000,
    )
