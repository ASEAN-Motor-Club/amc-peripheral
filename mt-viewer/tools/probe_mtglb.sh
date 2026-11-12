#!/bin/bash
# Probe: does mtglb produce stdout at all through this path?
set -uo pipefail
export PATH=/nix/store/8yqx3zsz5qbcffp2phmw91wjx2xcagq4-dotnet-sdk-wrapped-10.0.302/bin:$PATH
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export NUGET_PACKAGES=/opt/data/cache/nuget
WT=/var/lib/data/opencode/.kimaki/worktrees/59474658/-hy-jrvs-gt-a-qstn
cd /opt/data/workspace/mt-viewer/tools/mtglb
echo "--- usage (no args):"
dotnet bin/Release/net10.0/mtglb.dll
echo "--- ls dll:"
ls -la bin/Release/net10.0/mtglb.dll
echo "--- find star:"
dotnet bin/Release/net10.0/mtglb.dll --find "$WT" '*'
echo "rc=$?"
