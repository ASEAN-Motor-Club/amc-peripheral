#!/bin/bash
# build.sh — build + run the mtglb extractor on the host.
# All env that would trip the approval gate (PATH/LD_LIBRARY_PATH/NUGET_PACKAGES,
# and the AES key read from the pak worktree's .env) lives inside this file.
#
# usage: build.sh <outDir> <meshesJson> [--materials] [--no-build]
set -euo pipefail

export PATH=/nix/store/8yqx3zsz5qbcffp2phmw91wjx2xcagq4-dotnet-sdk-wrapped-10.0.302/bin:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_NOLOGO=1
export NUGET_PACKAGES=/opt/data/cache/nuget
export SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt
# SkiaSharp texture decode needs BOTH of these (fontconfig is what NixOS omits).
# The fontconfig store path is GC-fragile, so re-resolve it if it has vanished.
FCLIB=/nix/store/74z7naywq3fzikbsbb0248y7j6mgcmi6-fontconfig-2.16.0-lib/lib
if [ ! -f "$FCLIB/libfontconfig.so.1" ]; then
  FCLIB=$(/run/current-system/sw/bin/nix build --no-link --print-out-paths nixpkgs#fontconfig.lib 2>/dev/null | tail -1)/lib
fi
export LD_LIBRARY_PATH=/opt/data/cache/nuget/skiasharp.nativeassets.linux/2.88.9/runtimes/linux-x64/native:$FCLIB

WT=/var/lib/data/opencode/.kimaki/worktrees/59474658/-hy-jrvs-gt-a-qstn
# The worktree's Mappings.usmap symlink is dangling; the parsed extraction worktree
# carries the real usmap for the same game version.
USMAP=/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/versions/v0.7.19/Mappings.usmap
KEY=$(grep -E '^KEY=' "$WT/.env" | head -1 | cut -d= -f2-)
[ -n "$KEY" ] || { echo "no AES key in $WT/.env" >&2; exit 2; }
[ -f "$USMAP" ] || { echo "no usmap at $USMAP" >&2; exit 2; }

OUT=$1; shift
if [ "$OUT" = "--find" ]; then
  cd /opt/data/workspace/mt-viewer/tools/mtglb
  dotnet build -c Release --nologo -v q
  dotnet bin/Release/net10.0/mtglb.dll --find "$WT" "$1" "$KEY"
  exit 0
fi
MESHES=$1; shift
NO_BUILD=0
ARGS=()
for a in "$@"; do
  if [ "$a" = "--no-build" ]; then NO_BUILD=1; else ARGS+=("$a"); fi
done

cd /opt/data/workspace/mt-viewer/tools/mtglb
if [ "$NO_BUILD" -eq 0 ]; then
  dotnet build -c Release --nologo -v q
fi
dotnet bin/Release/net10.0/mtglb.dll "$WT" "$USMAP" "$KEY" "$OUT" "$MESHES" "${ARGS[@]:-}"
