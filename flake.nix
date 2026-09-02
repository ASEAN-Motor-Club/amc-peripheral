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
            nativeBuildInputs =
              (old.nativeBuildInputs or [])
              ++ [
                (final.resolveBuildSystem {setuptools = [];})
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

            # Disable pyrefly hook (too noisy, use manually instead)
            pyrefly = {
              enable = false;
            };
          };
        };

        devShells.default = let
          editablePythonSet = pythonSet.overrideScope editableOverlay;
          virtualenv = editablePythonSet.mkVirtualEnv "amc-peripheral-dev-env" workspace.deps.all;
        in
          pkgs.mkShell {
            packages =
              [
                virtualenv
                pkgs.uv
                pkgs.ffmpeg
                pkgs.pkg-config
                pkgs.gh
              ]
              ++ config.pre-commit.settings.enabledPackages;
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
              tls = {
                enable = lib.mkOption {
                  type = lib.types.bool;
                  default = true;
                  description = "Enable a native TLS (HTTPS) listen socket on Icecast.";
                };
                port = lib.mkOption {
                  type = lib.types.port;
                  default = 8443;
                  description = "Port Icecast serves the TLS (HTTPS) stream on.";
                };
                certFile = lib.mkOption {
                  type = lib.types.str;
                  default = "/var/lib/icecast/radio.combined.pem";
                  description = "Combined PEM (public+private key) Icecast reads for TLS.";
                };
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
            # Apply Sharry's overlay to make pkgs.sharry available, and the
            # icecast 2.5.0 overlay (+vendored libigloo) so the radio's :8443
            # native-TLS burst-on-connect race is fixed (see
            # docs/icecast-2.5-upgrade-handoff.md). This keeps nixpkgs pinned.
            nixpkgs.overlays = [
              inputs.sharry.overlays.default
              (import ./nix/overlay/icecast-2.5.nix)
            ];

            # Stable symlinks for static web packages so nginx config
            # doesn't change on every rebuild (prevents unnecessary reloads)
            # Sharry data dirs are merged into the same rules list to avoid
            # duplicate attribute definitions.
            systemd.tmpfiles.rules =
              [
                "d /var/www/nix-static 0755 root root -"
                "L+ /var/www/nix-static/radio-web - - - - ${cfg.radioWeb.package}"
                "L+ /var/www/nix-static/gov-web - - - - ${cfg.govWeb.package}"
                "L+ /var/www/nix-static/tire-web - - - - ${cfg.tireWeb.package}"
                "L+ /var/www/nix-static/code-web - - - - ${cfg.codeWeb.package}"
              ]
              ++ lib.optionals cfg.sharry.enable [
                "d /var/lib/sharry 0750 sharry sharry -"
                "d /var/lib/sharry/files 0750 sharry sharry -"
              ]
              ++ lib.optionals cfg.icecast.tls.enable [
                "d ${builtins.dirOf cfg.icecast.tls.certFile} 0755 root root -"
              ];

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
                  <sources>3</sources>
                  <queue-size>1048576</queue-size>
                  <client-timeout>30</client-timeout>
                  <header-timeout>15</header-timeout>
                  <source-timeout>30</source-timeout>
                  <burst-on-connect>1</burst-on-connect>
                  <burst-size>65536</burst-size>
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
                  <mount-name>/stream.opus</mount-name>
                  <username>source</username>
                  <password>${cfg.icecast.source.password}</password>
                  <max-listeners>500</max-listeners>
                  <public>1</public>
                  <stream-name>ASEAN Motor Club Radio (Opus)</stream-name>
                  <stream-description>Your home for automotive enthusiasm in Southeast Asia</stream-description>
                  <stream-url>https://aseanmotorclub.com/radio</stream-url>
                  <genre>Automotive</genre>
                </mount>

                <mount>
                  <mount-name>/fallback</mount-name>
                  <username>source</username>
                  <password>${cfg.icecast.source.password}</password>
                  <hidden>1</hidden>
                </mount>

                ${lib.optionalString cfg.icecast.tls.enable ''
                  <paths>
                    <ssl-certificate>${cfg.icecast.tls.certFile}</ssl-certificate>
                  </paths>

                  <listen-socket>
                    <port>${toString cfg.icecast.tls.port}</port>
                    <bind-address>${cfg.icecast.listen.address}</bind-address>
                    <ssl>1</ssl>
                  </listen-socket>

                  <http-headers>
                    <header name="Access-Control-Allow-Origin" value="*" />
                  </http-headers>
                ''}
              '';
            };

            # Icecast native TLS: combine ACME's separate cert+key into a single
            # PEM (Icecast's <ssl-certificate> wants both in one file) and make it
            # readable by the user Icecast drops to (nobody). Runs as root via
            # preStart (the icecast unit has no User= override), so it can read
            # /var/lib/acme and write the combined file before Icecast starts.
            systemd.services.icecast.preStart = lib.mkIf cfg.icecast.tls.enable (lib.mkAfter ''
              ${pkgs.coreutils}/bin/mkdir -p "$(dirname ${cfg.icecast.tls.certFile})"
              if [ -r /var/lib/acme/${cfg.nginx.domains.radio}/fullchain.pem ] \
                 && [ -r /var/lib/acme/${cfg.nginx.domains.radio}/key.pem ]; then
                ${pkgs.coreutils}/bin/cat \
                  /var/lib/acme/${cfg.nginx.domains.radio}/fullchain.pem \
                  /var/lib/acme/${cfg.nginx.domains.radio}/key.pem \
                  > ${cfg.icecast.tls.certFile}
                ${pkgs.coreutils}/bin/chown nobody:nogroup ${cfg.icecast.tls.certFile}
                ${pkgs.coreutils}/bin/chmod 600 ${cfg.icecast.tls.certFile}
              fi
            '');

            # Rebuild the combined PEM + restart Icecast whenever ACME renews
            # the radio cert (cert + key rotate together on renewal).
            systemd.paths.icecast-cert-refresh = lib.mkIf cfg.icecast.tls.enable {
              description = "Rebuild Icecast TLS bundle on ACME renewal";
              wantedBy = ["multi-user.target"];
              pathConfig.PathChanged = "/var/lib/acme/${cfg.nginx.domains.radio}/";
            };
            systemd.services.icecast-cert-refresh = lib.mkIf cfg.icecast.tls.enable {
              description = "Client for icecast-cert-refresh.path";
              wants = ["icecast.service"];
              after = ["icecast.service"];
              serviceConfig.Type = "oneshot";
              script = ''
                ${pkgs.coreutils}/bin/cat \
                  /var/lib/acme/${cfg.nginx.domains.radio}/fullchain.pem \
                  /var/lib/acme/${cfg.nginx.domains.radio}/key.pem \
                  > ${cfg.icecast.tls.certFile}
                ${pkgs.coreutils}/bin/chown nobody:nogroup ${cfg.icecast.tls.certFile}
                ${pkgs.coreutils}/bin/chmod 600 ${cfg.icecast.tls.certFile}
                ${pkgs.systemd}/bin/systemctl restart icecast.service
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
              # Cloudflare applies its default 4h static TTL to /sw.js and the
              # upstream service worker is cache-first with a fixed cache name
              # and no pruning. After a sharry upgrade, browsers can keep
              # running the stale webapp for hours (silent dead UI — e.g. the
              # signup page swallowing failed requests). Force revalidation.
              locations."= /sw.js" = {
                proxyPass = "http://127.0.0.1:${toString cfg.sharry.bindPort}";
                extraConfig = ''
                  proxy_set_header Host $host;
                  add_header Cache-Control "no-cache" always;
                '';
              };
            };

            # Radio ASEAN Web Interface (Discord Activity)
            services.nginx.virtualHosts.${cfg.nginx.domains.radio} = {
              enableACME = true;
              forceSSL = true;
              locations."/" = {
                root = "/var/www/nix-static/radio-web";
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
                root = "/var/www/nix-static/gov-web";
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
                root = "/var/www/nix-static/tire-web";
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
                TTS_PROVIDER = "google";
                MEMORY_DATA_DIR = "/var/lib/data/amc-memory";
                DEFAULT_AI_MODEL = "deepseek/deepseek-v4-flash-0731:nitro";
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
                MEMORY_DATA_DIR = "/var/lib/data/amc-memory-bot";
                DEFAULT_AI_MODEL = "deepseek/deepseek-v4-flash-0731";
                TRANSLATION_AI_MODEL = "openai/gpt-oss-120b";
                FINANCIAL_MINISTER_ROLE_ID = "1453698145950109779";
                ECONOMY_AUDIT_CHANNEL_ID = "1402660537619320872";
                COURT_CATEGORY_ID = "1498624085217902602";
                COURT_CHANNEL_ID = "1498624125227368468";
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

            # Malkuth Ban Trap Bot
            systemd.services.amc-ban-trap = {
              wantedBy = ["multi-user.target"];
              after = ["network.target"];
              description = "Malkuth Ban Trap Bot";
              restartIfChanged = false;
              # Non-secret config lives here as plain env vars (same pattern as
              # amc-bot's role/channel IDs). Only DISCORD_TOKEN_MALKUTH is a
              # secret and comes from the EnvironmentFile below.
              environment = {
                BAN_TRAP_CHANNEL_ID = "1529987241278177352";
                GUILD_ID = "1341775494026231859";
                # WARNING: verify these exempt role IDs before deploying — a
                # wrong value here can auto-ban staff who post in the trap.
                BAN_TRAP_ALLOWED_ROLE_IDS = "1395460420189421713,1496482029892669500";
                BAN_TRAP_ANNOUNCEMENT = "My apologies, but they had to go.";
                BAN_TRAP_AUTO_DELETE_ANNOUNCEMENT = "0";
                BAN_TRAP_CLEANUP_WINDOW_SECONDS = "60";
                BAN_TRAP_DELETE_DELAY_SECONDS = "5";
              };
              serviceConfig = {
                Type = "simple";
                Restart = "on-failure";
                RestartSec = "10";
                SyslogIdentifier = "amc-ban-trap";
                EnvironmentFile = "${cfg.environmentFile}";
              };
              script = ''
                ${self.packages.${pkgs.system}.default}/bin/amc_ban_trap
              '';
            };

            # Sharry file sharing service
            # NOTE: the DB must live on the local PostgreSQL — the upstream
            # module default is a demo H2 file in /tmp, which systemd-tmpfiles
            # deletes under the running server (accounts end up in an unlinked
            # inode and are lost on the next restart).
            services.sharry = lib.mkIf cfg.sharry.enable {
              enable = true;
              config = {
                base-url = cfg.sharry.baseUrl;
                bind = {
                  address = "127.0.0.1";
                  port = cfg.sharry.bindPort;
                };
                backend = {
                  # Invite-only registration: random users can't create accounts
                  # (and fill the disk). Invites are minted via the admin API:
                  #   POST /api/v2/admin/signup/newinvite {"password": "<this secret>"}
                  # -> {"success":true,"id":"<invite-key>"}; the key is single-use
                  # (deleted on use) and expires after signup.invite-time.
                  # NOTE: this secret lives in the store-rendered config
                  # (root-readable on a single-tenant host). If that ever stops
                  # being acceptable, move it to a runtime HOCON include from
                  # /run/agenix instead.
                  signup.mode = "invite";
                  signup.invite-password = "24b49bea95540cab43b7419c8b19aed87432de07920dfe92";
                  # pg_hba on this host trusts ::1 loopback TCP; verified against
                  # the running PostgreSQL 16 with sharry's bundled pgjdbc 42.7.5.
                  jdbc = {
                    url = "jdbc:postgresql://[::1]:5432/sharry";
                    user = "sharry";
                    password = "";
                  };
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

            # Provision the Sharry database/role on the local PostgreSQL
            # (list-typed NixOS options merge with any other module's config).
            services.postgresql.ensureDatabases = lib.mkIf cfg.sharry.enable ["sharry"];
            services.postgresql.ensureUsers = lib.mkIf cfg.sharry.enable [
              {
                name = "sharry";
                ensureDBOwnership = true;
              }
            ];

            # The upstream unit only waits for networking.target and sets no
            # Restart; order sharry after PostgreSQL so flyway migrations can't
            # race a not-yet-started database.
            systemd.services.sharry = lib.mkIf cfg.sharry.enable {
              after = ["postgresql.service"];
              wants = ["postgresql.service"];
            };
          };
        };
      };
    };
}
