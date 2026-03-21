{
  config,
  lib,
  ...
}:

let
  cfg = config.services.letta-traefik;
in
{
  options.services.letta-traefik = {
    enable = lib.mkEnableOption "Traefik reverse proxy for letta services";

    acmeEmail = lib.mkOption {
      type = lib.types.str;
      description = "Email for Let's Encrypt ACME registration.";
    };

    domain = lib.mkOption {
      type = lib.types.str;
      example = "ltgmc.space";
      description = "Base domain for the webhook entrypoint.";
    };

    webhookPath = lib.mkOption {
      type = lib.types.str;
      default = "/bot";
      description = "Path prefix for the bot webhook.";
    };

    dashboard.basicAuthUsersFile = lib.mkOption {
      type = lib.types.path;
      description = ''
        Path to htpasswd file for dashboard basicAuth.
        Each line: user:bcrypt_hash. Typically wired from sops secret.
      '';
    };

    gel.port = lib.mkOption {
      type = lib.types.port;
      default = 5656;
      description = "Local port where Gel container listens.";
    };

    ports = {
      bot = lib.mkOption {
        type = lib.types.port;
        default = 8090;
        description = "Local port where letta-bot container listens.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    services.traefik = {
      enable = true;

      staticConfigOptions = {
        entryPoints = {
          web = {
            address = ":80";
            http.redirections.entryPoint = {
              to = "websecure";
              scheme = "https";
            };
          };
          websecure.address = ":443";
        };

        certificatesResolvers.letsencrypt.acme = {
          email = cfg.acmeEmail;
          storage = "${config.services.traefik.dataDir}/acme.json";
          tlsChallenge = { };
        };

        api.dashboard = true;
      };

      dynamicConfigOptions.http = {
        routers = {
          letta-bot = {
            rule = "Host(`${cfg.domain}`) && PathPrefix(`${cfg.webhookPath}`)";
            service = "letta-bot";
            entryPoints = [ "websecure" ];
            tls.certResolver = "letsencrypt";
          };

          gel = {
            rule = "Host(`db.${cfg.domain}`)";
            service = "gel";
            entryPoints = [ "websecure" ];
            tls.certResolver = "letsencrypt";
          };

          traefik-dashboard = {
            rule = "Host(`tr.${cfg.domain}`)";
            service = "api@internal";
            entryPoints = [ "websecure" ];
            tls.certResolver = "letsencrypt";
            middlewares = [ "dashboard-auth" ];
          };
        };

        services = {
          letta-bot.loadBalancer.servers = [
            { url = "http://127.0.0.1:${toString cfg.ports.bot}"; }
          ];
          gel.loadBalancer.servers = [
            { url = "http://127.0.0.1:${toString cfg.gel.port}"; }
          ];
        };

        middlewares.dashboard-auth.basicAuth.usersFile = cfg.dashboard.basicAuthUsersFile;
      };
    };

    networking.firewall.allowedTCPPorts = [
      80
      443
    ];
  };
}
