-- Default den configuration values

let Types = ./Types.dhall

let defaultHealthcheck =
      None Types.Healthcheck

let defaultRestartPolicy =
      Some Types.RestartPolicy.Always

let defaultPorts =
      [ { port = 22, protocol = Some "tcp" }
      , { port = 3000, protocol = Some "tcp" }
      , { port = 4000, protocol = Some "tcp" }
      , { port = 5173, protocol = Some "tcp" }
      , { port = 8000, protocol = Some "tcp" }
      , { port = 8080, protocol = Some "tcp" }
      ]

let defaultVolumes =
      [ { mount = "/workspace", size = None Text } ]

let defaultGuixPackages =
      [ { name = "fish", version = None Text }
      , { name = "git", version = None Text }
      , { name = "helix", version = None Text }
      , { name = "zellij", version = None Text }
      , { name = "jj", version = None Text }
      , { name = "gh", version = None Text }
      , { name = "fzf", version = None Text }
      , { name = "ripgrep", version = None Text }
      , { name = "fd", version = None Text }
      , { name = "bat", version = None Text }
      ]

let defaultNixPackages =
      [ { name = "fish", version = None Text }
      , { name = "git", version = None Text }
      , { name = "helix", version = None Text }
      ]

in  { defaultHealthcheck
    , defaultRestartPolicy
    , defaultPorts
    , defaultVolumes
    , defaultGuixPackages
    , defaultNixPackages
    }
