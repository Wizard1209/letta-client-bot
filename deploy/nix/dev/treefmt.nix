{ inputs, ... }:
{
  imports = with inputs; [
    flake-root.flakeModule
    treefmt-nix.flakeModule
  ];
  perSystem =
    { config, ... }:
    {
      treefmt.config = {
        inherit (config.flake-root) projectRootFile;

        settings.global.excludes = [
          "*.md"
          "*.txt"
          "*.png"
          ".envrc"
          ".gitlint"
          "*.yaml"
        ];

        programs = {
          nixfmt.enable = true;
          deadnix.enable = true;
          statix.enable = true;
        };
      };
      formatter = config.treefmt.build.wrapper;
    };
}
