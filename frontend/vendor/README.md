# Pinned Chat encryption SDK

`chat-xdk-b4ce88b.tgz` is built from the MIT-licensed official [xdevplatform/chat-xdk](https://github.com/xdevplatform/chat-xdk/tree/b4ce88b1811acc15131f517678aea00d0d5c4933) source at commit `b4ce88b1811acc15131f517678aea00d0d5c4933`. It includes the upstream unreleased per-message-key reader; the published npm 0.5.2 reader cannot decode all current X web messages. The local package version is `0.5.2-web.b4ce88b`, not a published upstream release.

SHA-256: `65ca829725bc0b51cf4e4269eea539d52cf4dbcd3e0ab1a2ba887a5163a54a65`

The archive contains the JS wrapper, WASM module, MIT license, and third-party notices. It contains no X proprietary webpage bundles, accounts, PINs, or session captures. Compiler source paths are remapped during the build.

To rebuild with Rust and Node installed, run `python frontend/build-xdk.py` from the repository root. The script pins both source repositories and wasm-pack, uses the upstream Rust toolchain and Cargo.lock, and performs no X account operations. After rebuilding, run `npm install --prefix frontend ./frontend/vendor/chat-xdk-b4ce88b.tgz --ignore-scripts` to refresh lockfile integrity, then `npm run build --prefix frontend` and `node --test tests/test_chat_crypto.mjs`. Docker only needs the checked-in package and builds the browser bundle with `npm ci`.
