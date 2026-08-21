{ lib, inputs, ... }:
{
  perSystem =
    { system, ... }:
    {
      # customise pkgs
      _module.args.pkgs = import inputs.nixpkgs {
        inherit system inputs;
        config = {
          # allowUnfreePredicate = pkg: builtins.elem (lib.getName pkg) [ "" ];
        };
      };
      # make custom top-level lib available to all `perSystem` functions
      _module.args.lib = lib;
    };
}
