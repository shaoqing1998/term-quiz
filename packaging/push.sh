#!/usr/bin/env bash
# 推送代码到 GitHub（走 gh 的 API，绕开被墙的 git push）
#   bash packaging/push.sh ["提交说明"]
# 需要先 gh auth login。
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"

REPO="${REPO:-shaoqing1998/term-quiz}"
MSG="${1:-更新 $(date '+%F %H:%M')}"

git add -A >/dev/null 2>&1 || true

python3 - "$REPO" "$MSG" <<'PY'
import base64, json, subprocess, sys, os

repo, msg = sys.argv[1], sys.argv[2]

def gh(args, payload=None):
    cmd = ["gh", "api"] + args
    if payload is not None:
        cmd += ["--input", "-"]
    p = subprocess.run(cmd,
                       input=json.dumps(payload) if payload is not None else None,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"gh api 失败：{' '.join(cmd)}\n{p.stderr[:500]}")
    return json.loads(p.stdout) if p.stdout.strip() else {}

files = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       check=True).stdout.split()
files = [f for f in files if os.path.isfile(f)]
if not files:
    raise SystemExit("没有可推送的文件")

ref = gh([f"repos/{repo}/git/ref/heads/main"])
base = ref["object"]["sha"]
base_tree = gh([f"repos/{repo}/git/commits/{base}"])["tree"]["sha"]

tree = []
for f in files:
    blob = gh([f"repos/{repo}/git/blobs", "-X", "POST"], {
        "content": base64.b64encode(open(f, "rb").read()).decode(),
        "encoding": "base64",
    })
    tree.append({
        "path": f,
        "mode": "100755" if f.endswith(".sh") else "100644",
        "type": "blob",
        "sha": blob["sha"],
    })

t = gh([f"repos/{repo}/git/trees", "-X", "POST"], {"base_tree": base_tree, "tree": tree})
c = gh([f"repos/{repo}/git/commits", "-X", "POST"],
       {"message": msg, "tree": t["sha"], "parents": [base]})
gh([f"repos/{repo}/git/refs/heads/main", "-X", "PATCH"], {"sha": c["sha"], "force": True})
print(f"已推送 {len(files)} 个文件，commit {c['sha'][:8]}")
PY

echo "完成。需要发 Release 时："
echo "  gh release create vX.Y.Z dist/*.deb dist/*.tar.gz --title vX.Y.Z --notes '...'"
