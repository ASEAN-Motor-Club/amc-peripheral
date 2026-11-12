#!/bin/bash
# Evaluate the module far enough to prove the nginx vhost/location options are valid.
# (The flake exposes nixosModules, not nixosConfigurations, so we build a minimal
# system that imports it and read the generated nginx config back out.)
set -uo pipefail
W=$(/run/current-system/sw/bin/readlink -f /opt/data/workspace/amc-peripheral-wt-mt-viewer)
NIX=/run/current-system/sw/bin/nix
cd "$W" || exit 2

echo "--- nginx vhosts + the viewer locations:"
$NIX eval --impure --json --expr '
let
  f = builtins.getFlake ("git+file://" + toString '"$W"');
  lib = f.inputs.nixpkgs.lib;
  sys = lib.nixosSystem {
    system = "x86_64-linux";
    modules = [ f.nixosModules.default
                { nixpkgs.hostPlatform = "x86_64-linux";
                  system.stateVersion = "24.05";
                  services.amc-peripheral.enable = true;
                  services.amc-peripheral.environmentFile = "/dev/null";
                  services.amc-peripheral.cookiesPath = "/dev/null"; } ];
  };
  vh = sys.config.services.nginx.virtualHosts;
  www = vh."www.aseanmotorclub.com" or { locations = {}; };
in {
  hosts = builtins.attrNames vh;
  vehiclesSubdomain = builtins.filter (n: n == "vehicles.aseanmotorclub.com") (builtins.attrNames vh);
  wwwLocations = builtins.attrNames www.locations;
  wwwRoots = map (l: www.locations.${l}.root or "") (builtins.attrNames www.locations);
}' 2>&1 | tail -4
