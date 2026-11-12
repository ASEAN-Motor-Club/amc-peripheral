#!/bin/bash
# mtapi.sh — run the CUE4Parse reflection probe on the host.
set -euo pipefail
export PATH=/nix/store/8yqx3zsz5qbcffp2phmw91wjx2xcagq4-dotnet-sdk-wrapped-10.0.302/bin:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export NUGET_PACKAGES=/opt/data/cache/nuget
export SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt
cd /opt/data/workspace/mt-viewer/tools/mtapi
dotnet build -c Release --nologo -v q 2>&1 | grep -E " error " | head -10 || true
dotnet bin/Release/net10.0/mtapi.dll
