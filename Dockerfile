# devbox - Personal cloud dev environment
# Fedora-based to match local machine, with full TUI dev stack
FROM fedora:42

ARG TARGETARCH

# System packages
RUN dnf install -y \
    fish git git-lfs jq stow curl wget unzip tar gzip \
    openssh-server openssh-clients \
    gcc gcc-c++ make cmake pkgconf-pkg-config \
    openssl-devel zlib-devel \
    fd-find ripgrep bat fzf \
    procps-ng htop which diffutils \
    iproute iptables \
    && dnf clean all

# Helix editor
RUN dnf copr enable -y varlad/helix && dnf install -y helix && dnf clean all

# Zellij
RUN ARCH=$([ "$TARGETARCH" = "arm64" ] && echo "aarch64" || echo "x86_64") && \
    curl -fsSL "https://github.com/zellij-org/zellij/releases/latest/download/zellij-${ARCH}-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin/

# Jujutsu
RUN ARCH=$([ "$TARGETARCH" = "arm64" ] && echo "aarch64" || echo "x86_64") && \
    curl -fsSL "https://github.com/jj-vcs/jj/releases/latest/download/jj-v0.29.0-${ARCH}-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin/ --strip-components=1 jj-v0.29.0-${ARCH}-unknown-linux-musl/jj

# GitHub CLI
RUN dnf install -y 'dnf-command(config-manager)' && \
    dnf config-manager addrepo --from-repofile=https://cli.github.com/packages/rpm/gh-cli.repo && \
    dnf install -y gh && dnf clean all

# Tailscale
RUN curl -fsSL https://tailscale.com/install.sh | sh

# Nix (Determinate)
RUN curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix \
    | sh -s -- install linux --no-confirm --init none

# mise (runtime manager)
RUN curl https://mise.run | sh && \
    ln -s /root/.local/bin/mise /usr/local/bin/mise

# Create dev user
RUN useradd -m -s /usr/bin/fish -G wheel devbox && \
    echo "devbox ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers.d/devbox

# SSH server config
RUN mkdir -p /var/run/sshd && \
    ssh-keygen -A && \
    sed -i 's/#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config && \
    sed -i 's/#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config

# Workspace volume mount point
RUN mkdir -p /workspace && chown devbox:devbox /workspace

# Bootstrap script
COPY scripts/bootstrap.sh /usr/local/bin/bootstrap.sh
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/bootstrap.sh /usr/local/bin/entrypoint.sh

# Switch to dev user for dotfiles setup
USER devbox
WORKDIR /home/devbox

# Nix for devbox user
RUN . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh 2>/dev/null || true

# Pre-configure fish
RUN mkdir -p ~/.config/fish && \
    echo 'set -gx PATH /nix/var/nix/profiles/default/bin $HOME/.local/bin $HOME/.nix-profile/bin $PATH' \
    > ~/.config/fish/config.fish

USER root
EXPOSE 22 3000 4000 5173 8000 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
