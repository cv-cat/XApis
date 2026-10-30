"""Rebuild the pinned MIT Chat XDK browser package (Rust + Node required)."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

XDK_REV = "b4ce88b1811acc15131f517678aea00d0d5c4933"
JUICEBOX_REV = "2e0f544e3fd0bd0997a034f73c8efb6fade3690c"
root = Path(__file__).resolve().parent
out = root / "vendor"
out.mkdir(exist_ok=True)


def run(*args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def checkout(url, revision, directory):
    run("git", "init", "-q", str(directory))
    run("git", "fetch", "--depth", "1", url, revision, cwd=directory)
    run("git", "checkout", "--detach", "FETCH_HEAD", cwd=directory)


with tempfile.TemporaryDirectory(prefix="xapis-xdk-build-") as temporary:
    work = Path(temporary).resolve()
    source = work / "chat-xdk"
    checkout("https://github.com/xdevplatform/chat-xdk.git", XDK_REV, source)
    checkout(
        "https://github.com/juicebox-systems/juicebox-sdk.git",
        JUICEBOX_REV,
        work / "juicebox-sdk",
    )
    env = dict(os.environ)
    env["RUSTFLAGS"] = (
        f"--remap-path-prefix={Path.home()}=/build --remap-path-prefix={work}=/source"
    )
    run(
        "npm",
        "exec",
        "--yes",
        "--package=wasm-pack@0.13.1",
        "--",
        "wasm-pack",
        "build",
        "crates/wasm",
        "--target",
        "web",
        "--release",
        "--no-opt",
        "--",
        "--locked",
        cwd=source,
        env=env,
    )
    package = source / "crates/wasm/js"
    shutil.copytree(
        source / "crates/wasm/pkg",
        package / "pkg",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".*"),
    )
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(source / name, package / name)
    manifest = json.loads((package / "package.json").read_text())
    manifest["version"] = "0.5.2-web." + XDK_REV[:7]
    (package / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    run("npm", "pack", "--ignore-scripts", "--pack-destination", str(out), cwd=package)
    built = out / ("xdevplatform-chat-xdk-" + manifest["version"] + ".tgz")
    target = out / ("chat-xdk-" + XDK_REV[:7] + ".tgz")
    built.replace(target)
    print(target.name, hashlib.sha256(target.read_bytes()).hexdigest())
