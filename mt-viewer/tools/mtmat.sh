#!/bin/bash
# mtmat.sh — run the material-slot probe on the host (env lives here, not on the CLI).
set -euo pipefail
export PATH=/nix/store/8yqx3zsz5qbcffp2phmw91wjx2xcagq4-dotnet-sdk-wrapped-10.0.302/bin:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export NUGET_PACKAGES=/opt/data/cache/nuget
export SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt
WT=/var/lib/data/opencode/.kimaki/worktrees/59474658/-hy-jrvs-gt-a-qstn
USMAP=/opt/data/workspace/amc-server/mt-pak-extract-wt-0719/versions/v0.7.19/Mappings.usmap
KEY=$(grep -E '^KEY=' "$WT/.env" | head -1 | cut -d= -f2-)
cd /opt/data/workspace/mt-viewer/tools/mtmat
dotnet build -c Release --nologo -v q 2>&1 | grep -E "error" | head -20 || true
dotnet bin/Release/net10.0/mtmat.dll "$WT" "$USMAP" "$KEY" "${1:?meshes json}"
