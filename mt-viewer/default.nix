{pkgs, ...}: let
  # Motor Town vehicle 3D viewer — plain static HTML +
  # three.js (loaded from CDN) + exported GLB part meshes.
  # No build step: just copy the static assets into $out.
  package = pkgs.stdenv.mkDerivation {
    pname = "mt-viewer";
    version = "0.0.1";
    src = ./.;
    installPhase = ''
      runHook preInstall
      mkdir -p $out/glb
      cp index.html boxy.json preview.png $out/
      cp glb/*.glb $out/glb/
      runHook postInstall
    '';
    dontBuild = true;
  };
in {
  inherit package;
}