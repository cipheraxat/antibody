import os
import subprocess


def clone(url, filename, rev):
    # ruleid: os-system-formatted-command
    os.system("git clone --quiet %s %s" % (url, filename))
    # ruleid: os-system-formatted-command
    os.system(f"hg --cwd {filename} up -C -r {rev} -q")
    # ruleid: os-system-formatted-command
    subprocess.call("svn checkout {} {}".format(url, filename), shell=True)
    # ok: os-system-formatted-command
    subprocess.check_call(["git", "clone", "--quiet", url, filename])
    # ok: os-system-formatted-command
    os.system("git --version")
