#!/bin/bash
set -uo pipefail
W=$(/run/current-system/sw/bin/readlink -f /opt/data/workspace/amc-peripheral-wt-mt-viewer)
cd "$W" || exit 2
NIX=/run/current-system/sw/bin/nix
echo "--- packages:"
$NIX eval --json ".#packages.x86_64-linux" --apply 'builtins.attrNames' 2>&1 | tail -2
echo "--- build attempt (mt-viewer via module import):"
$NIX build --no-link --print-out-paths \
  --impure --expr 'let f = builtins.getFlake ("git+file://" + toString '"$W"'); pkgs = f.inputs.nixpkgs.legacyPackages.x86_64-linux; in pkgs.callPackage '"$W"'/mt-viewer {}' 2>&1 | tail -5
