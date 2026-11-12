#!/bin/bash
# mtmats.sh — resolve mesh material slots via CUE4Parse's graph param extractor.
# usage: mtmats.sh <meshesJson> <outDir>
set -euo pipefail
export PATH=/nix/store/8yqx3zsz5qbcffp2phmw91wjx2xcagq4-dotnet-sdk-wrapped-10.0.302/bin:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export NUGET_PACKAGES=/opt/data/cache/nuget
export SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt
FCLIB=/nix/store/74z7naywq3fzikbsbb0248y7j6mgcmi6-fontconfig-2.16.0-lib/lib
[ -f "$FCLIB/libfontconfig.so.1" ] || FCLIB=$(/run/current-system/sw/bin/nix build --no-link --print-out-paths nixpkgs#fontconfig.lib 2>/dev/null | tail -1)/lib
export LD_LIBRARY_PATH=/opt/data/cache/nuget/skiasharp.nativeassets.linux/2.88.9/runtimes/linux-x64/native:$FCLIB
WT=/var/lib/data/opencode/.kimaki/worktrees/59474658/-hy-jrvs-gt-a-qstn
USMAP=/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/versions/v0.7.19/Mappings.usmap
KEY=$(grep -E '^KEY=' "$WT/.env" | head -1 | cut -d= -f2-)
cd /opt/data/workspace/mt-viewer/tools/mtmats
dotnet build -c Release --nologo -v q 2>&1 | grep -E " error " | head -20 || true
dotnet bin/Release/net10.0/mtmats.dll "$WT" "$USMAP" "$KEY" "${1:?meshes json}" "${2:?outdir}" ${3:+"$3"}
