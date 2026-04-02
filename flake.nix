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

    sharry = {
      url = "github:eikek/sharry";
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

        # Override for packages missing build-system metadata in uv.lock
        # See: https://pyproject-nix.github.io/uv2nix/overriding/index.html
        pyprojectOverrides = final: prev: {
          pypika = prev.pypika.overrideAttrs (old: {
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ [
              (final.resolveBuildSystem { setuptools = []; })
            ];
          });
        };

        pythonSet =
          (pkgs.callPackage inputs.pyproject-nix.build.packages {
            python = pkgs.python312;
          }).overrideScope
          (
            lib.composeManyExtensions [
              inputs.pyproject-build-systems.overlays.wheel
              overlay
              pyprojectOverrides
            ]
          );
      in {
        # Pre-commit/pre-push hooks configuration
        # Note: hooks use a separate non-editable virtualenv (pythonSet) because:
        # - Hooks run outside the shell context, need stable Nix store paths
        # - DevShell uses editableOverlay which requires $REPO_ROOT (not available in hooks)
        pre-commit.settings = let
          hookVirtualenv = pythonSet.mkVirtualEnv "amc-peripheral-hook-env" workspace.deps.all;
        in {
          hooks = {
            # Built-in ruff hooks
            ruff = {
              enable = true;
              stages = ["pre-push"];
            };

            # Custom hook for pyrefly type checking
            # Wrap in sh -c to set PATH so pyrefly's fallback interpreter finds hookVirtualenv
            pyrefly = {
              enable = true;
              name = "pyrefly";
              description = "Type check with pyrefly";
              entry = "sh -c 'PATH=${hookVirtualenv}/bin:$PATH ${hookVirtualenv}/bin/pyrefly check .'";
              language = "system";
              pass_filenames = false;
              stages = ["pre-push"];
            };

            # Custom hook for pytest
            pytest = {
              enable = true;
              name = "pytest";
              description = "Run tests with pytest";
              entry = "${hookVirtualenv}/bin/pytest -q";
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
            inputs.sharry.nixosModules.default
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

            # Icecast streaming server
            icecast = {
              admin.password = lib.mkOption {
                type = lib.types.str;
                description = "Icecast admin password.";
              };
              source.password = lib.mkOption {
                type = lib.types.str;
                default = "hackme";
                description = "Icecast source password.";
              };
              listen.port = lib.mkOption {
                type = lib.types.port;
                default = 8000;
                description = "Port Icecast listens on.";
              };
              listen.address = lib.mkOption {
                type = lib.types.str;
                default = "0.0.0.0";
                description = "Address Icecast binds to.";
              };
            };

            # Nginx vhost domains
            nginx.domains = {
              radio = lib.mkOption {
                type = lib.types.str;
                default = "radio.aseanmotorclub.com";
                description = "Domain for the radio web UI.";
              };
              share = lib.mkOption {
                type = lib.types.str;
                default = "share.aseanmotorclub.com";
                description = "Domain for Sharry file sharing.";
              };
              gov = lib.mkOption {
                type = lib.types.str;
                default = "gov.aseanmotorclub.com";
                description = "Domain for the government portal.";
              };
              mods = lib.mkOption {
                type = lib.types.str;
                default = "mods.aseanmotorclub.com";
                description = "Domain for the tire mod creator web app.";
              };
            };

            # Radio web UI package
            radioWeb.package = lib.mkOption {
              type = lib.types.package;
              default = (import ./radio-web {inherit pkgs;}).package;
              description = "Radio web UI static build package.";
            };

            # Code web UI package (OpenCode Discord Activity wrapper)
            codeWeb.package = lib.mkOption {
              type = lib.types.package;
              default = (import ./code-web {inherit pkgs;}).package;
              description = "Code web UI static build package (Discord Activity).";
            };

            # Government portal static site
            govWeb.package = lib.mkOption {
              type = lib.types.package;
              default = (import ./gov-web {inherit pkgs;}).package;
              description = "Government portal static build package.";
            };

            # Tire mod creator static site
            tireWeb.package = lib.mkOption {
              type = lib.types.package;
              default = (import ./tire-web {inherit pkgs;}).package;
              description = "Tire mod creator static build package.";
            };

            # Sharry file sharing service
            sharry = {
              enable = lib.mkEnableOption "Sharry file sharing service";
              baseUrl = lib.mkOption {
                type = lib.types.str;
                default = "https://share.aseanmotorclub.com";
                description = "External URL where Sharry is accessible.";
              };
              bindPort = lib.mkOption {
                type = lib.types.port;
                default = 9090;
                description = "Port Sharry binds to locally.";
              };
            };
          };


          config = lib.mkIf cfg.enable {
            # Apply Sharry's overlay to make pkgs.sharry available
            nixpkgs.overlays = [ inputs.sharry.overlays.default ];

            # Icecast streaming server
            services.icecast = {
              enable = true;
              hostname = "aseanmotorclub.com";
              admin.password = cfg.icecast.admin.password;

              listen.address = cfg.icecast.listen.address;
              listen.port = cfg.icecast.listen.port;

              extraConf = ''
                <location>ASEAN Motor Club</location>
                <admin>admin@aseanmotorclub.com</admin>

                <limits>
                  <clients>500</clients>
                  <sources>2</sources>
                  <queue-size>4194304</queue-size>
                  <client-timeout>300</client-timeout>
                  <header-timeout>15</header-timeout>
                  <source-timeout>30</source-timeout>
                  <burst-on-connect>1</burst-on-connect>
                  <burst-size>1048576</burst-size>
                </limits>

                <mount>
                  <mount-name>/stream</mount-name>
                  <username>source</username>
                  <password>${cfg.icecast.source.password}</password>
                  <max-listeners>500</max-listeners>
                  <public>1</public>
                  <stream-name>ASEAN Motor Club Radio</stream-name>
                  <stream-description>Your home for automotive enthusiasm in Southeast Asia</stream-description>
                  <stream-url>https://aseanmotorclub.com/radio</stream-url>
                  <genre>Automotive</genre>
                  <fallback-mount>/fallback</fallback-mount>
                  <fallback-override>1</fallback-override>
                </mount>


                <mount>
                  <mount-name>/fallback</mount-name>
                  <username>source</username>
                  <password>${cfg.icecast.source.password}</password>
                  <hidden>1</hidden>
                </mount>
              '';
            };

            # Sharry file sharing — Nginx vhost
            services.nginx.virtualHosts.${cfg.nginx.domains.share} = {
              enableACME = true;
              forceSSL = true;
              locations."/" = {
                proxyPass = "http://127.0.0.1:${toString cfg.sharry.bindPort}";
                extraConfig = ''
                  proxy_http_version 1.1;
                  proxy_set_header Upgrade $http_upgrade;
                  proxy_set_header Connection "upgrade";
                  proxy_set_header Host $host;
                  proxy_set_header X-Real-IP $remote_addr;
                  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                  proxy_set_header X-Forwarded-Proto $scheme;
                  proxy_buffering off;
                  client_max_body_size 105M;
                  proxy_send_timeout 300s;
                  proxy_read_timeout 300s;
                  send_timeout 300s;
                '';
              };
            };

            # Radio ASEAN Web Interface (Discord Activity)
            services.nginx.virtualHosts.${cfg.nginx.domains.radio} = {
              enableACME = true;
              forceSSL = true;
              locations."/" = {
                root = "${cfg.radioWeb.package}";
                tryFiles = "$uri $uri/index.html /index.html";
                extraConfig = ''
                  add_header Cache-Control "public, max-age=3600";
                '';
              };
              locations."/api" = {
                proxyPass = "http://127.0.0.1:7001/api";
                extraConfig = ''
                  proxy_set_header Host $host;
                  proxy_set_header X-Real-IP $remote_addr;
                  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                  proxy_set_header X-Forwarded-Proto $scheme;
                '';
              };
              locations."/stream" = {
                proxyPass = "http://127.0.0.1:${toString cfg.icecast.listen.port}/stream";
                extraConfig = ''
                  proxy_http_version 1.1;
                  proxy_connect_timeout 5s;
                  proxy_read_timeout 86400s;
                  proxy_send_timeout 86400s;
                  proxy_set_header Upgrade $http_upgrade;
                  proxy_set_header Connection "keep-alive";
                  proxy_set_header Host $host;
                  proxy_set_header X-Real-IP $remote_addr;
                  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                  proxy_buffering off;
                  proxy_cache off;
                  gzip off;
                  access_log off;
                  add_header X-Accel-Buffering no;
                  add_header Access-Control-Allow-Origin "*";
                '';
              };
              # Icecast admin UI — accessible only over Tailscale
              locations."/icecast/" = {
                proxyPass = "http://127.0.0.1:${toString cfg.icecast.listen.port}/";
                extraConfig = ''
                  allow 100.64.0.0/10;
                  deny all;
                  proxy_set_header Host $host;
                  proxy_set_header X-Real-IP $remote_addr;
                  # Rewrite absolute paths in Icecast XSL/HTML responses
                  sub_filter_types text/xml text/xsl text/html application/xhtml+xml;
                  sub_filter_once off;
                  sub_filter 'href="/' 'href="/icecast/';
                  sub_filter 'src="/' 'src="/icecast/';
                  sub_filter 'url(/' 'url(/icecast/';
                  sub_filter '="/status' '="/icecast/status';
                  sub_filter '="/admin' '="/icecast/admin';
                '';
              };
            };

            # Government Portal (static site)
            services.nginx.virtualHosts.${cfg.nginx.domains.gov} = {
              enableACME = true;
              forceSSL = true;
              locations."/" = {
                root = "${cfg.govWeb.package}";
                tryFiles = "$uri $uri/index.html /index.html";
                extraConfig = ''
                  add_header Cache-Control "public, max-age=3600";
                '';
              };
            };

            # Tire Mod Creator (static site + build API)
            services.nginx.virtualHosts.${cfg.nginx.domains.mods} = {
              enableACME = true;
              forceSSL = true;
              locations."/" = {
                root = "${cfg.tireWeb.package}";
                tryFiles = "$uri $uri/index.html /index.html";
                extraConfig = ''
                  add_header Cache-Control "public, max-age=3600";
                '';
              };
              locations."/api" = {
                proxyPass = "http://127.0.0.1:7002/api";
                extraConfig = ''
                  proxy_set_header Host $host;
                  proxy_set_header X-Real-IP $remote_addr;
                  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                  proxy_set_header X-Forwarded-Proto $scheme;
                  proxy_read_timeout 120s;
                  client_max_body_size 50M;
                '';
              };
            };

            systemd.services.amc-radio = {
              wantedBy = ["multi-user.target"];
              after = ["network.target" "motortown-server.service"];
              description = "AMC Radio Service";
              environment = {
                PLAYLIST_PATH = "/var/lib/radio/playlist";
                DENO_PATH = "${pkgs.deno}/bin/deno";
                RADIO_PATH = "/var/lib/radio/";
                REQUESTS_PATH = "/var/lib/radio/requests";
                SONGS_PATH = "/var/lib/radio/songs";
                JINGLES_PATH = "/var/lib/radio/jingles";
                GOOGLE_APPLICATION_CREDENTIALS = "/var/lib/radio/adc.json";
                OPUS_PATH = "${pkgs.libopus}/lib/libopus.so";
                YT_COOKIES_PATH = "${cfg.cookiesPath}";
                RADIO_DB_PATH = "${cfg.dbPath}";
                TTS_PROVIDER = "qwen3";
              };
              restartIfChanged = false;
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
              after = ["network.target" "motortown-server.service" "amc-radio.service"];
              description = "AMC Bot";
              environment = {
                RADIO_DB_PATH = "${cfg.dbPath}";
                GAME_DB_PATH = "/var/lib/motortown/gamedata.db";
                YT_COOKIES_PATH = "${cfg.cookiesPath}";
                DENO_PATH = "${pkgs.deno}/bin/deno";
                # DEFAULT_AI_MODEL = "xiaomi/mimo-v2-flash:free";
                TRANSLATION_AI_MODEL = "openai/gpt-oss-120b";
              };
              restartIfChanged = false;
              serviceConfig = {
                Type = "notify";
                NotifyAccess = "all";
                Restart = "always";
                RestartSec = "10";
                CPUQuota = "80%";
                WatchdogSec = "120";
                TimeoutStopSec = "30";
                TimeoutStartSec = "120";
                EnvironmentFile = "${cfg.environmentFile}";
              };
              script = ''
                ${self.packages.${pkgs.system}.default}/bin/amc_bot
              '';
            };


            # Tire Mod Build API
            systemd.services.amc-mods = {
              wantedBy = ["multi-user.target"];
              after = ["network.target"];
              description = "AMC Tire Mod Build API";
              environment = {
                # These will be set when mt-pak-extract toolchain is packaged as a flake input.
                # For now, they default to binaries available in PATH.
                # TIRE_BUILDER_DOTNET_TOOL = "...";
                # TIRE_BUILDER_MOD_PACK = "...";
                # TIRE_BUILDER_MOD_EXPLORE = "...";
                # TIRE_BUILDER_TEMPLATES_DIR = "...";
              };
              restartIfChanged = false;
              serviceConfig = {
                Type = "simple";
                Restart = "on-failure";
                RestartSec = "10";
                DynamicUser = true;
                PrivateTmp = true;
                ProtectSystem = "strict";
                ReadWritePaths = ["/tmp"];
                EnvironmentFile = "${cfg.environmentFile}";
              };
              script = ''
                ${self.packages.${pkgs.system}.default}/bin/amc_mods
              '';
            };

            # Sharry file sharing service
            services.sharry = lib.mkIf cfg.sharry.enable {
              enable = true;
              config = {
                base-url = cfg.sharry.baseUrl;
                bind = {
                  address = "127.0.0.1";
                  port = cfg.sharry.bindPort;
                };
                backend = {
                  signup.mode = "open";
                  files = {
                    default-store = "filesystem";
                    stores.filesystem = {
                      enabled = true;
                      type = "file-system";
                      directory = "/var/lib/sharry/files";
                    };
                  };
                };
                webapp.chunk-size = "100M";
              };
            };

            # Create data directory for Sharry
            systemd.tmpfiles.rules = lib.mkIf cfg.sharry.enable [
              "d /var/lib/sharry 0750 sharry sharry -"
              "d /var/lib/sharry/files 0750 sharry sharry -"
            ];
          };
        };
      };
    };
}
