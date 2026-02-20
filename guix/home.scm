;; Devbox home environment configuration
;; Declarative user environment — packages, shell config, dotfiles, env vars.
;; Apply with: guix home reconfigure home.scm
;; Test with:  guix home container home.scm
(use-modules
 (gnu home)
 (gnu home services)
 (gnu home services shells)
 (gnu packages)
 (gnu services)
 (guix gexp))

(home-environment
 ;; ── Packages ────────────────────────────────────────────────────
 (packages
  (map specification->package+output
       (list
        ;; Shell & terminal
        "fish" "zellij" "zoxide" "fzf" "gum"

        ;; Editor
        "helix"

        ;; Version control
        "git" "git-lfs" "jujutsu"

        ;; CLI tools
        "ripgrep" "fd" "bat" "jq" "stow" "curl" "htop"

        ;; Build essentials
        "gcc-toolchain" "make" "cmake" "pkg-config"

        ;; Networking
        "openssh")))

 ;; ── Services ────────────────────────────────────────────────────
 (services
  (list
   ;; Fish shell
   (service
    home-fish-service-type
    (home-fish-configuration
     (aliases
      '(("g" . "git")
        ("j" . "jj")
        ("hx" . "helix")
        ("ll" . "ls -la")
        ("la" . "ls -A")))
     (environment-variables
      '(("EDITOR" . "hx")
        ("VISUAL" . "hx")
        ("PAGER" . "bat --paging=always")))
     (config
      (list
       (plain-file "fish-extra.fish"
                   "# Zoxide integration
if command -vq zoxide
    zoxide init fish | source
end

# Atuin integration
if command -vq atuin
    atuin init fish | source
end

# Workspace shortcut
if test -d /workspace
    abbr -a ws 'cd /workspace'
end
")))))

   ;; Environment variables
   (simple-service
    'devbox-env-vars
    home-environment-variables-service-type
    '(("EDITOR" . "hx")
      ("VISUAL" . "hx")
      ("GUIX_LOCPATH" . "$HOME/.guix-home/profile/lib/locale"))))))
