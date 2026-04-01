#!/usr/bin/env bash
set -euo pipefail

echo "==> Starting den (Guix variant)..."

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
export PATH="/var/guix/profiles/per-user/root/den-profile/bin:$PATH"
export GUIX_PROFILE="/var/guix/profiles/per-user/root/den-profile"
export GUIX_LOCPATH="$GUIX_PROFILE/lib/locale"

# ── SSH server ───────────────────────────────────────────────────
/usr/sbin/sshd -D &
echo "==> SSH server started"

# ── Tailscale ────────────────────────────────────────────────────
if [ -n "${TAILSCALE_AUTHKEY:-}" ]; then
    mkdir -p /workspace/.tailscale
    # Railway containers generally do not expose /dev/net/tun; run in userspace mode.
    tailscaled --tun=userspace-networking --state=/workspace/.tailscale/tailscaled.state &
    sleep 2

    HOSTNAME="${DEN_NAME:-den}"
    tailscale up \
        --authkey="$TAILSCALE_AUTHKEY" \
        --hostname="$HOSTNAME" \
        --ssh \
        --accept-routes

    echo "==> Tailscale connected as $HOSTNAME"
    echo "==> SSH: ssh den@${HOSTNAME}.<your-tailnet>.ts.net"
else
    echo "==> TAILSCALE_AUTHKEY not set, skipping Tailscale"
fi

# ── First-boot bootstrap ────────────────────────────────────────
if [ ! -f /home/den/.den-bootstrapped ]; then
    su - den -c "/usr/local/bin/bootstrap-guix.sh"
    touch /home/den/.den-bootstrapped
    chown den:den /home/den/.den-bootstrapped
fi

echo "==> den (Guix) ready!"
echo "==> guix-daemon is running — use guix shell, guix install, guix home reconfigure"
echo "==> Connect: ssh den@${DEN_NAME:-den}.<tailnet>.ts.net"

exec tail -f /dev/null
