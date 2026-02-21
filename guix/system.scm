;; Den full system configuration
;; Produces a complete Guix System Docker image.
;; This is the "dream" — the entire OS defined in Scheme.
;;
;; Build:
;;   guix time-machine -C channels.scm -- system image \
;;     --image-type=docker system.scm
;;
;; Or build a VM:
;;   guix time-machine -C channels.scm -- system vm system.scm
(use-modules
 (gnu)
 (gnu packages)
 (gnu system)
 (gnu services networking)
 (gnu services ssh)
 (gnu services shepherd))

(use-package-modules
 terminals shells version-control
 text-editors commencement cmake pkg-config
 search curl admin ssh tls networking
 less base)

(operating-system
 (host-name "den")
 (timezone "America/Toronto")
 (locale "en_CA.utf8")

 ;; Minimal bootloader (not used for Docker, required by schema)
 (bootloader (bootloader-configuration
              (bootloader grub-bootloader)
              (targets '("/dev/sdX"))))

 ;; Minimal filesystem (not used for Docker, required by schema)
 (file-systems (cons (file-system
                      (device "none")
                      (mount-point "/")
                      (type "tmpfs"))
                     %base-file-systems))

 ;; ── Packages (system-wide) ──────────────────────────────────
 (packages
  (append
   (map specification->package
        '("fish" "zellij" "helix"
          "git" "git-lfs" "jujutsu"
          "ripgrep" "fd" "bat" "jq" "fzf" "gum"
          "stow" "curl" "wget" "htop" "diffutils"
          "gcc-toolchain" "make" "cmake" "pkg-config"
          "openssh" "iproute2" "iptables"
          "zoxide" "glibc-locales"
          "nss-certs"))
   %base-packages))

 ;; ── Users ───────────────────────────────────────────────────
 (users
  (cons*
   (user-account
    (name "den")
    (group "users")
    (home-directory "/home/den")
    (shell (file-append (specification->package "fish") "/bin/fish"))
    (supplementary-groups '("wheel")))
   %base-user-accounts))

 ;; Allow passwordless sudo for den
 (sudoers-file
  (plain-file "sudoers"
              "root ALL=(ALL) ALL
%wheel ALL=(ALL) NOPASSWD: ALL
"))

 ;; ── Services ────────────────────────────────────────────────
 (services
  (append
   (list
    ;; SSH server
    (service openssh-service-type
             (openssh-configuration
              (permit-root-login #f)
              (password-authentication? #f)))

    ;; Guix daemon is started by default in Guix System
    ;; No need to configure it explicitly

    ;; NSCD for name resolution
    (service nscd-service-type))

   %base-services)))
