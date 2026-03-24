{pkgs, ...}: let
  package = pkgs.buildNpmPackage rec {
    pname = "code-web";
    version = "0.0.1";
    src = ./.;

    # Regenerate after changing npm packages:
    #   cd amc-peripheral/code-web && npm install
    #   nix run nixpkgs#prefetch-npm-deps -- package-lock.json > _npmDepsHash
    # npmDepsHash = pkgs.lib.fakeHash;
    npmDepsHash = pkgs.lib.readFile ./_npmDepsHash;
    npmFlags = "--ignore-scripts --include=dev";
    makeCacheWritable = true;

    NODE_ENV = "production";

    # Discord Activity client ID — injected at build time via SvelteKit $env/static/public
    # This is the devbot's Discord Application ID
    PUBLIC_DISCORD_CLIENT_ID = "1456206285472010272";

    buildPhase = ''
      runHook preBuild
      npm run build
      runHook postBuild
    '';

    # adapter-static outputs to build/ by default
    installPhase = ''
      runHook preInstall
      mkdir -p $out
      cp -r build/* $out/
      runHook postInstall
    '';
  };
in {
  inherit package;
}
