#!/usr/bin/env bash
set -euo pipefail

echo "==> Starting devbox (Guix variant)..."

# ── Guix daemon ──────────────────────────────────────────────────
# The heart of the Guix system — enables guix shell, guix install,
# guix home reconfigure, guix pack, etc. at runtime.
echo "==> Starting guix-daemon..."
/var/guix/profiles/per-user/root/current-guix/bin/guix-daemon \
    --build-users-group=guixbuild \
    --disable-chroot &
sleep 2
echo "==> guix-daemon running (guix shell, guix install, etc. available)"

# Source the Guix profile so all manifest packages are on PATH
export PATH="/var/guix/profiles/per-user/root/devbox-profile/bin:$PATH"
export GUIX_PROFILE="/var/guix/profiles/per-user/root/devbox-profile"
export GUIX_LOCPATH="$GUIX_PROFILE/lib/locale"

# ── SSH server ───────────────────────────────────────────────────
/usr/sbin/sshd -D &
echo "==> SSH server started"

# ── Tailscale ────────────────────────────────────────────────────
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
    echo "==> SSH: ssh devbox@${HOSTNAME}.<your-tailnet>.ts.net"
else
    echo "==> TAILSCALE_AUTHKEY not set, skipping Tailscale"
fi

# ── First-boot bootstrap ────────────────────────────────────────
if [ ! -f /home/devbox/.devbox-bootstrapped ]; then
    su - devbox -c "/usr/local/bin/bootstrap-guix.sh"
    touch /home/devbox/.devbox-bootstrapped
    chown devbox:devbox /home/devbox/.devbox-bootstrapped
fi

echo "==> devbox (Guix) ready!"
echo "==> guix-daemon is running — use guix shell, guix install, guix home reconfigure"
echo "==> Connect: ssh devbox@${DEVBOX_NAME:-devbox}.<tailnet>.ts.net"

exec tail -f /dev/null
