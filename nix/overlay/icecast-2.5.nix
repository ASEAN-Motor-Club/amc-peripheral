# Overlay supplying icecast 2.5.0 (+ vendored libigloo dep) over the pinned
# nixpkgs. Keeps the rest of nixpkgs frozen at the pinned rev (3e2499d5) —
# the "method 2" targeted-upgrade path from docs/icecast-2.5-upgrade-handoff.md.
#
# Why this exists: icecast 2.4.4's native-TLS burst-on-connect has a write
# backpressure race that drops remote clients on the :8443 stream. 2.5.0 fixes
# it ("Changed handling of TLS clients on high buffer pressure"). We overlay
# only the icecast package + its new libigloo dep rather than bumping the whole
# nixpkgs input (which would re-evaluate the entire peripheral config against
# a newer nixpkgs, and drag in stale flake.lock submodule pins).
#
# Wire into flake.nix alongside the sharry overlay:
#   nixpkgs.overlays =
#     [ inputs.sharry.overlays.default (import ./nix/overlay/icecast-2.5.nix) ];
#
# deps: rhash + pkg-config already exist in the pinned rev (rhash 1.4.4);
# only libbigloo is vendored (nix/pkgs/libigloo.nix).

final: prev: {
  libigloo = final.pkgs.callPackage ../pkgs/libigloo.nix { };
  icecast = final.pkgs.callPackage ../pkgs/icecast.nix { };
}