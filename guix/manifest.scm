;; Den package manifest
;; All packages for the dev environment, declared in one place.
;; Change this list → rebuild → redeploy = new environment.
;;
;; Usage:
;;   guix shell -m manifest.scm              # test locally
;;   guix pack -f docker -m manifest.scm     # build docker image
(specifications->manifest
 '(;; Shell & terminal
   "fish"
   "zellij"
   "zoxide"
   "fzf"
   "gum"

   ;; Editor
   "helix"

   ;; Version control
   "git"
   "git-lfs"
   "jujutsu"

   ;; Core CLI tools
   "ripgrep"
   "fd"
   "bat"
   "jq"
   "stow"
   "curl"
   "wget"
   "htop"
   "diffutils"

   ;; Build essentials
   "gcc-toolchain"
   "make"
   "cmake"
   "pkg-config"
   "openssl"

   ;; Networking
   "openssh"
   "iproute2"
   "iptables"

   ;; Locales
   "glibc-locales"))
