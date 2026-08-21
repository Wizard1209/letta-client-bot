{
  perSystem =
    {
      pkgs,
      config,
      # self',
      inputs',
      ...
    }:
    {
      devShells.default = pkgs.mkShell {
        shellHook = ''
          ${config.pre-commit.installationScript}
        '';

        packages = [
        ]
        ++ (with pkgs; [
          git
          nix
          nixfmt
          nixos-anywhere
          sops
          ssh-to-age
          wget
          deploy-rs
        ])
        ++ (with inputs'; [
          deploy-rs.packages.default
        ]);
      };
    };
}
