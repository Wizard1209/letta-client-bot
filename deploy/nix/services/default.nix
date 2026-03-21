{
  flake.nixosModules = {
    service-openssh = import ./openssh.nix;
    service-traefik = import ./traefik.nix;
    service-letta-bot = import ./letta-bot.nix;
  };
}
