{
  self,
  inputs,
  lib,
  ...
}:
let
  inherit (inputs)
    nixpkgs
    deploy-rs
    ;

  mkHost =
    {
      name,
      system,
      extraConfig ? null,
    }:
    nixpkgs.lib.nixosSystem {
      inherit system;
      specialArgs = {
        inherit
          self
          inputs
          lib
          ;
      };
      modules = [
        self.nixosModules."nixos-${name}"
      ]
      ++ lib.optional (extraConfig != null) extraConfig;
    };

  # Each host must specify its system explicitly
  hosts = {
    dev = {
      system = "x86_64-linux";
      hostname = "5.252.118.97";
    };
  };

  nixosConfigurations = lib.mapAttrs (
    name: hostArgs:
    mkHost {
      inherit name;
      inherit (hostArgs) system;
    }
  ) hosts;

  deployNodes = lib.mapAttrs (
    name: hostArgs:
    let
      nixosConfig = nixosConfigurations.${name};
    in
    {
      hostname = hostArgs.hostname or name;
      profiles.system = {
        user = "root";
        path = deploy-rs.lib.${hostArgs.system}.activate.nixos nixosConfig;
      };
    }
  ) hosts;
in
{
  flake.nixosModules = {
    # Shared modules
    common = import ./common.nix;
    minimal = import ./minimal.nix;

    nixos-dev = import ./dev/configuration.nix;
  };

  flake = {
    inherit nixosConfigurations;
    deploy.nodes = deployNodes;
  };
}
