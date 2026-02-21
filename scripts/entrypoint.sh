#!/usr/bin/env bash
set -euo pipefail

echo "==> Starting den entrypoint..."

# Start Nix daemon
if [ -f /nix/var/nix/profiles/default/lib/systemd/system/nix-daemon.service ]; then
    /nix/var/nix/profiles/default/bin/nix-daemon &
    echo "==> Nix daemon started"
fi

# Start SSH server
/usr/sbin/sshd -D &
echo "==> SSH server started"

# Start Tailscale
if [ -n "${TAILSCALE_AUTHKEY:-}" ]; then
    mkdir -p /workspace/.tailscale
    tailscaled --state=/workspace/.tailscale/tailscaled.state &
    sleep 2

    HOSTNAME="${DEN_NAME:-den}"
    tailscale up \
        --authkey="$TAILSCALE_AUTHKEY" \
        --hostname="$HOSTNAME" \
        --ssh \
        --accept-routes

    echo "==> Tailscale connected as $HOSTNAME"
    echo "==> SSH available at: ssh den@${HOSTNAME}.<your-tailnet>.ts.net"
else
    echo "==> TAILSCALE_AUTHKEY not set, skipping Tailscale"
fi

# Run bootstrap for the den user (first-time setup)
if [ ! -f /home/den/.den-bootstrapped ]; then
    su - den -c "/usr/local/bin/bootstrap.sh"
    touch /home/den/.den-bootstrapped
    chown den:den /home/den/.den-bootstrapped
fi

echo "==> den ready!"
echo "==> Connect via: ssh den@${DEN_NAME:-den}.<tailnet>.ts.net"

# Keep container alive
exec tail -f /dev/null
