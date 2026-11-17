# camofox-browser patches

`server.js` is NOT part of this repo: it belongs to the upstream camofox-browser project
(`@askjo/camofox-browser`, built into the image from `./camofox-browser`). Patches this skill
relies on are kept here so anyone can re-apply them to their own copy:

    cd camofox-browser && patch -p1 < ../camofox-patches/inline-upload.patch
    docker compose restart camofox-browser     # server.js is bind-mounted (compose.example.yaml)

## inline-upload.patch
`/tabs/:id/upload` and `/uploadViaChooser` additionally accept `filename` + `content_base64`
(instead of `path`), so ANY remote client can upload without a shared /uploads mount.
Bytes go to a per-tab temp dir deleted on tab close (+ 1h sweep). Basename only; <= 10 MB
(`CAMOFOX_UPLOAD_MAX_BYTES`); pdf/doc/docx/txt/rtf/odt/png/jpg/jpeg/gif/webp. `path` mode unchanged.

Client side is automatic (`cfx.post`): `CFX_UPLOAD_MODE=auto|path|inline` (default auto = inline
when `CFX_URL` is a remote host, mount mode when the server is on the same host).
