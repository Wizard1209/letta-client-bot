{
  self,
  inputs,
  lib,
  config,
  pkgs,
  ...
}:
{
  system.configurationRevision = toString (
    self.rev or self.dirtyRev or self.lastModified or "unknown"
  );

  nixpkgs.config.allowUnfree = true;

  nix = {
    registry = lib.mapAttrs (_: value: { flake = value; }) inputs;
    nixPath = lib.mapAttrsToList (key: value: "${key}=${value.to.path}") config.nix.registry;

    settings = {
      trusted-users = [
        "root"
        "@wheel"
      ];
      experimental-features = "nix-command flakes";
      substituters = [
        "https://cache.nixos.org"
      ];
      builders-use-substitutes = true;
      connect-timeout = lib.mkDefault 5;
    };
  };

  networking.firewall.enable = true;

  networking.enableIPv6 = false;

  security.sudo.enable = true;
  security.sudo.wheelNeedsPassword = false;

  users.mutableUsers = false;

  time.timeZone = "UTC";

  # List packages installed in system profile
  environment.systemPackages = with pkgs; [
    wget
    curl
    vim
    htop
    nix-info
  ];

  boot.loader.grub.configurationLimit = lib.mkDefault 5;
  boot.loader.systemd-boot.configurationLimit = lib.mkDefault 5;

  programs.bash.completion.enable = true;

  systemd.services.trim-profiles = {
    description = "Delete older profiles";
    serviceConfig.Type = "oneshot";
    script = ''
      ${pkgs.nix}/bin/nix-env --delete-generations +3 --profile /nix/var/nix/profiles/system
    '';
    startAt = "03:00";
  };

  # https://nixos.wiki/wiki/FAQ/When_do_I_update_stateVersion
  system.stateVersion = "25.11";
}
