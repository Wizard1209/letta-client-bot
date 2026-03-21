{
  self,
  inputs,
  ...
}:
{
  imports = [
    ./disk-config.nix
    ./services.nix
    inputs.sops-nix.nixosModules.sops
    inputs.disko.nixosModules.disko
  ]
  ++ (with self.nixosModules; [
    common
    minimal
    module-tcp-tweaks
    service-openssh
    users-vizqq
    users-wizard
    users-github-ci
  ]);

  sops.defaultSopsFile = ./secrets.yaml;

  hardware.facter.reportPath = ./facter.json;
  hardware.facter.detected.dhcp.enable = false;

  nix.settings = {
    auto-optimise-store = true;
    # no need this data for small vps
    keep-outputs = false;
    keep-derivations = false;
    keep-build-log = false;
  };

  networking = {
    hostName = "e7a9";
    domain = "ru";
    useDHCP = false;

    interfaces.eth0 = {
      ipv4.addresses = [
        {
          address = "5.252.118.97";
          prefixLength = 24;
        }
      ];
    };

    defaultGateway = "5.252.118.1";
    nameservers = [
      "8.8.8.8"
      "8.8.4.4"
    ];
    usePredictableInterfaceNames = false;
  };

  boot = {
    loader.grub.enable = true;
    initrd.systemd.tpm2.enable = false;
  };
}
