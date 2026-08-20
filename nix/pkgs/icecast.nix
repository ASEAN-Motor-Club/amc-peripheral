# Vendored icecast 2.5.0, overriding the pinned 2.4.4 package.
#
# Ported from upstream nixpkgs package/by-name/ic/icecast/package.nix at the
# 2.5.0 release. Deliberately keeps the upstream derivation shape unchanged
# (finalAttrs, SRI hash, nativeBuildInputs/buildInputs) so it is a faithful,
# minimal diff from the known-good upstream package and easy to drop once the
# whole nixpkgs input is bumped past the 2.5.0 inclusion.
#
# Drawn here because icecast 2.5.0 fixes the native-TLS burst-on-connect write
# backpressure race that caused the :8443 remote drops (see
# docs/icecast-2.5-upgrade-handoff.md). We keep nixpkgs pinned and overlay only
# this package (+ its new dep libigloo) so blast radius stays minimal.
#
# New deps vs the pinned 2.4.4 derivation:
#   + pkg-config (native)
#   + libigloo  (vendored, see libigloo.nix)
#   + rhash     (already in pinned rev, 1.4.4)
{
  lib,
  stdenv,
  fetchurl,
  pkg-config,
  curl,
  libigloo,
  libkate,
  libopus,
  libtheora,
  libvorbis,
  libxml2,
  libxslt,
  rhash,
  speex,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "icecast";
  version = "2.5.0";

  src = fetchurl {
    url = "https://downloads.xiph.org/releases/icecast/icecast-${finalAttrs.version}.tar.gz";
    hash = "sha256-2aoHx0Ka7BnZUP9v1CXDcfdxWM00/yIPwZGywYbGfHo=";
  };

  nativeBuildInputs = [ pkg-config ];

  buildInputs = [
    curl
    libigloo
    libkate
    libopus
    libtheora
    libvorbis
    libxml2
    libxslt
    rhash
    speex
  ];

  meta = {
    description = "Server software for streaming multimedia";
    mainProgram = "icecast";

    longDescription = ''
      Icecast is a streaming media server which currently supports
      Ogg (Vorbis and Theora), Opus, WebM and MP3 audio streams.
      It can be used to create an Internet radio station or a privately
      running jukebox and many things in between. It is very versatile
      in that new formats can be added relatively easily and supports
      open standards for communication and interaction.
    '';

    homepage = "https://www.icecast.org";
    license = lib.licenses.gpl2Plus;
    maintainers = with lib.maintainers; [ jcumming ];
    platforms = with lib.platforms; unix;
  };
})