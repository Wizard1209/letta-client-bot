{
  self,
  config,
  lib,
  ...
}:

let
  cfg = config.services.letta-bot;
in
{
  options.services.letta-bot = {
    enable = lib.mkEnableOption "Letta Telegram bot with Gel database";

    image = lib.mkOption {
      type = lib.types.str;
      default = "ghcr.io/wizard1209/letta-client-bot:latest";
      description = "Container image for the letta bot.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8090;
      description = "Host port for the bot webhook (bound to 127.0.0.1).";
    };

    secretsEnvFile = lib.mkOption {
      type = lib.types.path;
      description = "Path to env file with secrets (TELEGRAM_BOT_TOKEN, LETTA_API_KEY, etc).";
    };

    webhookHost = lib.mkOption {
      type = lib.types.str;
      description = "Webhook hostname for Telegram.";
    };

    webhookPath = lib.mkOption {
      type = lib.types.str;
      default = "/bot";
      description = "Webhook URL path.";
    };

    adminIds = lib.mkOption {
      type = lib.types.listOf lib.types.int;
      default = [ ];
      description = "Telegram user IDs with admin access.";
    };

    loggingLevel = lib.mkOption {
      type = lib.types.enum [
        "DEBUG"
        "INFO"
        "WARNING"
        "ERROR"
        "CRITICAL"
      ];
      default = "INFO";
      description = "Bot logging level.";
    };

    pullPolicy = lib.mkOption {
      type = lib.types.enum [
        "always"
        "missing"
        "never"
        "newer"
      ];
      default = "always";
      description = "Image pull policy for the bot container.";
    };

    gel = {
      image = lib.mkOption {
        type = lib.types.str;
        default = "geldata/gel:latest";
        description = "Gel container image.";
      };

      port = lib.mkOption {
        type = lib.types.port;
        default = 5656;
        description = "Host port for Gel (bound to 127.0.0.1).";
      };

      passwordFile = lib.mkOption {
        type = lib.types.path;
        description = "Path to env file containing GEL_SERVER_PASSWORD.";
      };

      dbschemaPath = lib.mkOption {
        type = lib.types.path;
        default = "${self}/dbschema";
        description = "Path to the dbschema directory with migrations.";
      };

      dataDir = lib.mkOption {
        type = lib.types.str;
        default = "gel-data";
        description = "Podman volume name for persistent Gel data.";
      };

    };
  };

  config = lib.mkIf cfg.enable {
    virtualisation.podman.enable = true;
    virtualisation.oci-containers.backend = "podman";

    systemd.services.podman-network-letta = {
      description = "Create letta Podman network";
      wantedBy = [ "multi-user.target" ];
      before = [
        "podman-gel.service"
        "podman-letta-bot.service"
      ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      path = [ config.virtualisation.podman.package ];
      script = ''
        podman network exists letta || podman network create letta
      '';
    };

    virtualisation.oci-containers.containers = {
      gel = {
        image = cfg.gel.image;
        autoStart = true;

        environment = {
          GEL_SERVER_HTTP_ENDPOINT_SECURITY = "optional";
          GEL_SERVER_BINARY_ENDPOINT_SECURITY = "optional";
          GEL_SERVER_TLS_CERT_MODE = "generate_self_signed";
          GEL_SERVER_ADMIN_UI = "enabled";
          GEL_DOCKER_APPLY_MIGRATIONS = "always";
        };

        environmentFiles = [ cfg.gel.passwordFile ];

        volumes = [
          "${cfg.gel.dbschemaPath}:/dbschema:ro"
          "${cfg.gel.dataDir}:/var/lib/gel/data"
        ];

        ports = [
          "127.0.0.1:${toString cfg.gel.port}:5656"
        ];

        extraOptions = [
          "--network=letta"
          "--health-cmd=curl -f http://localhost:5656/server/status/ready || exit 1"
          "--health-interval=120s"
          "--health-start-period=60s"
          "--health-timeout=10s"
          "--health-retries=3"
        ];

        podman = {
          sdnotify = "healthy";
        };
      };

      letta-bot = {
        image = cfg.image;
        autoStart = true;
        pull = cfg.pullPolicy;

        dependsOn = [ "gel" ];

        environment = {
          WEBHOOK_HOST = cfg.webhookHost;
          WEBHOOK_PATH = cfg.webhookPath;
          GEL_HOST = "gel";
          GEL_PORT = toString cfg.gel.port;
          GEL_CLIENT_TLS_SECURITY = "insecure";
          LOGGING_LEVEL = cfg.loggingLevel;
        }
        // lib.optionalAttrs (cfg.adminIds != [ ]) {
          ADMIN_IDS = lib.concatMapStringsSep "," toString cfg.adminIds;
        };

        environmentFiles = [ cfg.secretsEnvFile ];

        capabilities.NET_BIND_SERVICE = true;

        ports = [
          "127.0.0.1:${toString cfg.port}:80"
        ];

        extraOptions = [ "--network=letta" ];
      };
    };
  };
}
