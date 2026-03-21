{ pkgs, lib, ... }:
{
  services.openssh = {
    enable = true;
    banner = "";

    settings.PermitRootLogin = lib.mkForce "no";
    settings.X11Forwarding = false;
    settings.KbdInteractiveAuthentication = false;
    settings.PasswordAuthentication = false;
    settings.UseDns = false;
    # unbind gnupg sockets if they exists
    settings.StreamLocalBindUnlink = true;
    # disable compression (potential attack vector)
    settings.Compression = false;

    # post-quantum key exchange
    settings.KexAlgorithms = [
      "mlkem768x25519-sha256"
      "sntrup761x25519-sha512@openssh.com"
      "curve25519-sha256"
      "curve25519-sha256@libssh.org"
    ];

    # modern ciphers prioritizing aes-gcm and chacha20-poly1305
    settings.Ciphers = [
      "chacha20-poly1305@openssh.com"
      "aes256-gcm@openssh.com"
      "aes128-gcm@openssh.com"
      "aes256-ctr"
      "aes128-ctr"
    ];

    # only etm macs for protection against timing attacks
    settings.Macs = [
      "hmac-sha2-512-etm@openssh.com"
      "hmac-sha2-256-etm@openssh.com"
      "umac-128-etm@openssh.com"
    ];

    hostKeys = [
      {
        path = "/etc/ssh/ssh_host_ed25519_key";
        type = "ed25519";
      }
    ];
  };

  networking.firewall.allowedTCPPorts = [ 22 ];

  services.fail2ban = {
    enable = true;
    bantime-increment.enable = true;
    jails.sshd.settings.filter = "sshd[mode=normal]";
    ignoreIP = [
    ];
  };

  environment.systemPackages = [ pkgs.kitty.terminfo ];
}
