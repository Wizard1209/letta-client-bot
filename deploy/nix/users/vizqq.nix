{
  users.users = {
    vizqq = {
      description = "Radik Islamov";
      isNormalUser = true;
      openssh.authorizedKeys.keys = [
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAxADjBmQT2x1NTfq9rjhgQgOA6RikfWWiznVpo5RH1e cardno:FFFE_A9B20E0F"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILZPEhcSv5wlCgc8b4KiVYxPBp7G9behxzIwRLSiiw+P"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHM8whIcMxZru0sp0cmNZmoF5VYZYg2KbUlXnIvK8ege"
      ];
      extraGroups = [
        "wheel"
        "networkmanager"
      ];
    };
  };
}
