import subprocess
import tempfile
import os
from harness import patch


def _init_repo(d):
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "t"], check=True)
    with open(os.path.join(d, "seed.txt"), "w") as f:
        f.write("seed\n")
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "seed"], check=True)


def test_apply_new_file_diff():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        diff = (
            "diff --git a/hello.txt b/hello.txt\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/hello.txt\n"
            "@@ -0,0 +1 @@\n"
            "+hello harness\n"
        )
        ok, msg = patch.apply_diff(d, diff)
        assert ok, msg
        assert os.path.exists(os.path.join(d, "hello.txt"))


def test_empty_diff_rejected():
    with tempfile.TemporaryDirectory() as d:
        _init_repo(d)
        ok, msg = patch.apply_diff(d, "   ")
        assert not ok and msg == "empty diff"
