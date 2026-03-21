{
  modulesPath,
  lib,
  ...
}:
let
  inherit (lib) mkDefault;
in
{
  imports = [
    (modulesPath + "/profiles/minimal.nix")
  ];

  xdg.menus.enable = mkDefault false;

  fonts.fontconfig.enable = mkDefault false;

  # Print the URL instead on servers
  environment.variables.BROWSER = "echo";
}
