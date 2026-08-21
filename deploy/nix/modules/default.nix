{
  flake.nixosModules = {
    module-tcp-tweaks = import ./tcp-tweaks.nix;
  };
}
