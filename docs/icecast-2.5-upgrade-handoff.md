# Icecast 2.5 Upgrade Handoff

Status: **not started** — future work. Written 2026-08-20 after the
native-TLS `:8443` drop was diagnosed and worked around.

## Why a handoff exists

In Aug 2026, `https://radio.aseanmotorclub.com:8443/stream.opus` and
`/stream` dropped remote clients after a few seconds (~40KB, mid-burst) while
localhost streamed fine. The root cause was **Icecast 2.4.4's native-TLS
burst-on-connect race**: over real WAN RTT the socket send-buffer fills
mid-burst and the native TLS partial-write path
(`connection_send_ssl` → `SSL_ERROR_WANT_WRITE` → `send_to_listener` breaks on
`bytes<=0`) drops the connection. Localhost masked it (zero RTT).

**Current workaround (shipped, live):** `burst-on-connect 0`, `burst-size 0`
in `flake.nix` `extraConf`. This makes native TLS stable but costs instant
playback startup — clients buffer a few seconds. The upgrade below is the way
to potentially bring the burst back.

### Fix history (for context)
- PR #25: queue-size 65536→1MiB. Hygiene, not the cause.
- PR #26: loglevel 4 (diagnostic, later reverted in #29).
- PR #27: sources 2→3 — real, gave `/stream.opus` a live source.
- PR #28: **burst-on-connect 0** — the actual drop fix. Confirmed by Meehoi.
- PR #29: removed loglevel 4.

## Does 2.5 fix the burst issue?

**Likely yes.** Icecast 2.5.0 changelog explicitly lists:
> "Changed handling of TLS clients on high buffer pressure"

That is precisely the burst-write-backpressure path that broke in 2.4.4. On
2.5 we can test **re-enabling** `burst-on-connect 1` / `burst-size 65536`
and drop the workaround. 2.5 also requires TLS ≥ 1.2 (we already are) and
adds libigloo as a dependency.

## Is the upgrade trivial?

**One-line icecast version bump: NO — the icecast package comes from the
`nixos-unstable` nixpkgs input**, which is pinned in `flake.lock`
(rev `3e2499d5`, 2025-12-25 — predates the 2.5.0 release ~Dec 31). Actually
upgrading icecast means either:

1. **Bump the whole nixpkgs input** (`nix flake lock --update-input nixpkgs`)
   — a full NixOS system update, not just icecast. All packages update, and
   the whole peripheral config re-evaluates against a newer nixpkgs. Medium
   risk, needs full regenerate + test. This is the only way to get the
   nixpkgs 2.5.0 package without overlaying your own.

2. **Overlay icecast 2.5.0** (`nixpkgs.overlays = [...(self: super: {
     icecast = super.icecast.overrideAttrs (...) }]` or a source override in
     `package.nix`) while keeping the rest of nixpkgs pinned. Lower blast
     radius — icecast 2.5.0 source builds cleanly, needs pkg-config + deps
     `libigloo libopus libvorbis libtheora libkate libxml2 libxslt rhash
     speex curl`. This is the safer, targeted path.

So: **not a trivial version bump.** Prefer approach 2 (overlay) to avoid a
whole-system nixpkgs update on the peripheral host.

## Config compatibility (2.4 → 2.5)

Low risk. Icecast 2.5 reads **both 2.4.x and 2.5.x style configuration**
(per Xiph wiki on the new auth system). Our `extraConf` uses standard
`<limits>`, `<mount>`, `<listen-socket><ssl>`, `<http-headers>` — all
compatible. The nginx `sub_filter` rewrites on `/icecast/` (status.xsl) may
need a check if the 2.5 status page markup changed.

Things to verify after upgrade:
- `sources=3` still respected (main mount /stream + /stream.opus + /fallback).
- `queue-size=1048576` still > `burst-size` (65536 if re-enabled) — keep this
  relationship.
- cert reload: 2.4.4 needed a restart to reload the ACME cert (we have a
  `systemd.path` `icecast-cert-refresh` unit that restarts icecast on cert
  change). 2.5 advertises cert reload support — can drop that unit if it works.
- nginx `/stream` proxy + `/icecast/` sub_filter still render.

UTC 2026-08-20, current live config (gen 92+): `sources=3`, `queue-size=1MiB`,
`burst-on-connect=0`, `burst-size=0`. All three mounts fed by liquidsoap
(/stream, /stream.opus) + fallback script (/fallback).