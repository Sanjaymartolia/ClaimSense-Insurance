"""Make your own copy of the kit:  python course/scripts/new_student.py <yourname>

Creates exercises/<yourname>/. Work only in there; course/ is the template and is
never edited by students.
"""

import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
name = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
dest = KIT.parent / "exercises" / name
if dest.exists():
    sys.exit(f"{dest} already exists")
shutil.copytree(
    KIT,
    dest,
    ignore=shutil.ignore_patterns(
        ".index", ".cache", ".state", "runs", "__pycache__", "new_student.py"
    ),
)
print(f"created {dest}\nnext: cd {dest} && python scripts/build_index.py --force")
