{ self, config, ... }:
{
  imports = with self.nixosModules; [
    service-traefik
    service-letta-bot
  ];

  sops.secrets = {
    telegram-bot-token = { };
    letta-project-id = { };
    letta-api-key = { };
    gel-password = { };
    openai-api-key = { };
    traefik-htpasswd = {
      owner = "traefik";
    };
  };

  sops.templates."bot-secrets.env".content = ''
    TELEGRAM_BOT_TOKEN=${config.sops.placeholder.telegram-bot-token}
    LETTA_PROJECT_ID=${config.sops.placeholder.letta-project-id}
    LETTA_API_KEY=${config.sops.placeholder.letta-api-key}
    OPENAI_API_KEY=${config.sops.placeholder.openai-api-key}
    GEL_PASSWORD=${config.sops.placeholder.gel-password}
  '';

  sops.templates."gel.env".content = ''
    GEL_SERVER_PASSWORD=${config.sops.placeholder.gel-password}
  '';

  services.letta-traefik = {
    enable = true;
    domain = "e7a9.ru";
    acmeEmail = "trash@vizqq.cc";
    dashboard.basicAuthUsersFile = config.sops.secrets.traefik-htpasswd.path;
  };

  services.letta-bot = {
    enable = true;
    image = "ghcr.io/Wizard1209/letta-client-bot:latest";
    webhookHost = "e7a9.ru";
    webhookPath = "/bot";
    adminIds = [ 744956396 ];
    secretsEnvFile = config.sops.templates."bot-secrets.env".path;
    gel.passwordFile = config.sops.templates."gel.env".path;
  };
}
