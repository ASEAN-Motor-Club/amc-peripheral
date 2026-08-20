# Vendored libigloo, required by icecast 2.5.x.
# Not present in the pinned nixpkgs (rev 3e2499d5, nixos-unstable, 2025-12-25),
# so the overlay supplies it. Ported unmodified from upstream nixpkgs
# pkgs/by-name/li/libigloo/package.nix (icecast 2.5.0 dependency).
# Depends on rhash, which IS already present in the pinned rev (1.4.4).
{
  lib,
  stdenv,
  fetchurl,
  rhash,
  icecast,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "libigloo";
  version = "0.9.5";

  src = fetchurl {
    url = "https://downloads.xiph.org/releases/igloo/libigloo-${finalAttrs.version}.tar.gz";
    hash = "sha256-6iLpEZ96IYiBD5kQDFFVxnYtRZWuITuawp5ptPC4cok=";
  };

  buildInputs = [ rhash ];

  doCheck = true;

  meta = {
    description = "Generic C framework used and developed by the Icecast project";
    license = lib.licenses.gpl2Only;
    inherit (icecast.meta) maintainers;
  };
})