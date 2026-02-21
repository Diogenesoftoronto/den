;; Den home environment configuration
;; Declarative user environment — packages, shell config, dotfiles, env vars.
;; Apply with: guix home reconfigure home.scm
;; Test with:  guix home container home.scm
(use-modules
 (gnu home)
 (gnu home services)
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
   ;; Environment variables
   (simple-service
    'den-env-vars
    home-environment-variables-service-type
    '(("EDITOR" . "hx")
      ("VISUAL" . "hx")
      ("GUIX_LOCPATH" . "$HOME/.guix-home/profile/lib/locale"))))))
