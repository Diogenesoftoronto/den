#!/usr/bin/env bash
set -euo pipefail

echo "==> Starting devbox entrypoint..."

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
    tailscaled --state=/var/lib/tailscale/tailscaled.state &
    sleep 2

    HOSTNAME="${DEVBOX_NAME:-devbox}"
    tailscale up \
        --authkey="$TAILSCALE_AUTHKEY" \
        --hostname="$HOSTNAME" \
        --ssh \
        --accept-routes

    echo "==> Tailscale connected as $HOSTNAME"
    echo "==> SSH available at: ssh devbox@${HOSTNAME}.<your-tailnet>.ts.net"
else
    echo "==> TAILSCALE_AUTHKEY not set, skipping Tailscale"
fi

# Run bootstrap for the devbox user (first-time setup)
if [ ! -f /home/devbox/.devbox-bootstrapped ]; then
    su - devbox -c "/usr/local/bin/bootstrap.sh"
    touch /home/devbox/.devbox-bootstrapped
    chown devbox:devbox /home/devbox/.devbox-bootstrapped
fi

echo "==> devbox ready!"
echo "==> Connect via: ssh devbox@${DEVBOX_NAME:-devbox}.<tailnet>.ts.net"

# Keep container alive
exec tail -f /dev/null
