{ ... }:
{
  perSystem =
    { config, pkgs, ... }:
    {
      formatter =
        let
          inherit (config.pre-commit.settings) package configFile;
        in
        pkgs.writeShellScriptBin "pre-commit-run" ''
          ${pkgs.lib.getExe package} run --all-files --config ${configFile}
        '';
    };
}
