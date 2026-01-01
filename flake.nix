{
  description = "amc-peripheral flake using uv2nix";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";

    git-hooks-nix = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = inputs @ {
    flake-parts,
    self,
    ...
  }:
    flake-parts.lib.mkFlake {inherit inputs;} {
      imports = [
        inputs.git-hooks-nix.flakeModule
      ];

      systems = ["x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin"];

      perSystem = {
        config,
        self',
        inputs',
        pkgs,
        system,
        ...
      }: let
        inherit (inputs.nixpkgs) lib;
        workspace = inputs.uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ./.;};

        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        editableOverlay = workspace.mkEditablePyprojectOverlay {
          root = "$REPO_ROOT";
        };

        pythonSet =
          (pkgs.callPackage inputs.pyproject-nix.build.packages {
            python = pkgs.python312;
          }).overrideScope
          (
            lib.composeManyExtensions [
              inputs.pyproject-build-systems.overlays.wheel
              overlay
            ]
          );
      in {
        # Pre-commit/pre-push hooks configuration
        pre-commit.settings = {
          hooks = {
            # Built-in ruff hooks
            ruff = {
              enable = true;
              stages = ["pre-push"];
            };

            # Custom hook for pyrefly type checking
            pyrefly = {
              enable = true;
              name = "pyrefly";
              description = "Type check with pyrefly";
              entry = "uv run pyrefly check .";
              language = "system";
              pass_filenames = false;
              stages = ["pre-push"];
            };

            # Custom hook for pytest
            pytest = {
              enable = true;
              name = "pytest";
              description = "Run tests with pytest";
              entry = "uv run pytest -q";
              language = "system";
              pass_filenames = false;
              stages = ["pre-push"];
            };
          };
        };

        devShells.default = let
          editablePythonSet = pythonSet.overrideScope editableOverlay;
          virtualenv = editablePythonSet.mkVirtualEnv "amc-peripheral-dev-env" workspace.deps.all;
        in
          pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
              pkgs.ffmpeg
              pkgs.pkg-config
              pkgs.gh
            ] ++ config.pre-commit.settings.enabledPackages;
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = editablePythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
              ${config.pre-commit.installationScript}
            '';
          };

        packages.default = pythonSet.mkVirtualEnv "amc-peripheral-env" workspace.deps.default;
      };

      flake = {
        nixosModules.default = {
          config,
          lib,
          pkgs,
          ...
        }: let
          cfg = config.services.amc-peripheral;
        in {
          imports = [
            ./radio/liquidsoap.nix
          ];
          options.services.amc-peripheral = {
            enable = lib.mkEnableOption "AMC Peripheral Services";
            environmentFile = lib.mkOption {
              type = lib.types.path;
              description = "Path to the environment file containing secrets.";
            };
            cookiesPath = lib.mkOption {
              type = lib.types.path;
              description = "Path to the cookies file.";
            };
            dbPath = lib.mkOption {
              type = lib.types.str;
              default = "/var/lib/radio/radio.db";
              description = "Path to the sqlite database.";
            };
            jarvisRepoPath = lib.mkOption {
              type = lib.types.str;
              description = "Path to the monorepo source in Nix store for JARVIS.";
            };
            jarvisAiModel = lib.mkOption {
              type = lib.types.str;
              default = "anthropic/claude-3.7-sonnet";
              description = "Default AI model for JARVIS.";
            };
          };


          config = lib.mkIf cfg.enable {
            systemd.services.amc-radio = {
              wantedBy = ["multi-user.target"];
              after = ["network.target" "motortown-server.service"];
              description = "AMC Radio Service";
              environment = {
                PLAYLIST_PATH = "/var/lib/radio/playlist";
                FFPROBE_PATH = "${pkgs.ffmpeg}/bin/ffprobe";
                DENO_PATH = "${pkgs.deno}/bin/deno";
                RADIO_PATH = "/var/lib/radio/";
                REQUESTS_PATH = "/var/lib/radio/requests";
                SONGS_PATH = "/var/lib/radio/songs";
                JINGLES_PATH = "/var/lib/radio/jingles";
                FFMPEG_PATH = "${pkgs.ffmpeg}/bin/ffmpeg";
                GOOGLE_APPLICATION_CREDENTIALS = "/var/lib/radio/adc.json";
                OPUS_PATH = "${pkgs.libopus}/lib/libopus.so";
                YT_COOKIES_PATH = "${cfg.cookiesPath}";
                RADIO_DB_PATH = "${cfg.dbPath}";
              };
              restartIfChanged = true;
              serviceConfig = {
                Type = "simple";
                Restart = "on-failure";
                RestartSec = "10";
                RuntimeMaxSec = "26400";
                EnvironmentFile = "${cfg.environmentFile}";
              };
              script = ''
                ${self.packages.${pkgs.system}.default}/bin/amc_radio
              '';
            };

            systemd.services.amc-bot = {
              wantedBy = ["multi-user.target"];
              after = ["network.target" "motortown-server.service"];
              description = "AMC Bot";
              environment = {
                FFMPEG_PATH = "${pkgs.ffmpeg}/bin/ffmpeg";
                FFPROBE_PATH = "${pkgs.ffmpeg}/bin/ffprobe";
                RADIO_DB_PATH = "${cfg.dbPath}";
              };
              restartIfChanged = true;
              serviceConfig = {
                Type = "simple";
                Restart = "on-failure";
                RestartSec = "10";
                EnvironmentFile = "${cfg.environmentFile}";
              };
              script = ''
                ${self.packages.${pkgs.system}.default}/bin/amc_bot
              '';
            };

            systemd.services.amc-jarvis = {
              wantedBy = ["multi-user.target"];
              after = ["network.target"];
              description = "AMC JARVIS Bot";
              environment = {
                JARVIS_REPO_PATH = cfg.jarvisRepoPath;
                JARVIS_AI_MODEL = cfg.jarvisAiModel;
              };
              restartIfChanged = true;
              serviceConfig = {
                Type = "simple";
                Restart = "on-failure";
                RestartSec = "10";
                EnvironmentFile = "${cfg.environmentFile}";
              };
              script = ''
                ${self.packages.${pkgs.system}.default}/bin/amc_jarvis
              '';
            };
          };
        };
      };
    };
}
