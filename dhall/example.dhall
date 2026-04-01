-- Example den configuration using Dhall
-- This file demonstrates the type-safe configuration approach

let Types = ./Types.dhall

let Defaults = ./default.dhall

-- Define a Guix-based environment with full declarative package management
let myGuixDen =
      { name = "myproject"
      , backend = Types.Backend.Guix
      , dockerfile = None Text  -- Will use Dockerfile.guix by default
      , restartPolicy = Some Types.RestartPolicy.Always
      , healthcheck = None Types.Healthcheck
      , ports = Defaults.defaultPorts
      , volumes = Defaults.defaultVolumes
      , resources = None Types.Resource
      , secrets =
          [ Types.Secret.FromEnv
              { name = "TAILSCALE_AUTHKEY", envVar = "TAILSCALE_AUTHKEY" }
          , Types.Secret.FromEnv
              { name = "GH_TOKEN", envVar = "GH_TOKEN" }
          ]
      , guix = Some
          { channels = Some
              [ { name = "guix"
                , url = "https://git.savannah.gnu.org/git/guix.git"
                , branch = "master"
                }
              , { name = "nonguix"
                , url = "https://gitlab.com/nonguix/nonguix.git"
                , branch = "master"
                }
              , { name = "tailscale"
                , url = "https://github.com/tailscale/guix.git"
                , branch = "main"
                }
              ]
          , packages =
                Defaults.defaultGuixPackages
              # [ { name = "python", version = None Text }
                , { name = "node", version = None Text }
                , { name = "rust", version = None Text }
                , { name = "go", version = None Text }
                ]
          , services = Some [ "tailscale", "sshd" ]
          }
      , nix = None Types.NixConfig
      , environment =
          [ { mapKey = "DEN_NAME", mapValue = "den-myproject" }
          , { mapKey = "DEN_BACKEND", mapValue = "guix" }
          , { mapKey = "RAILWAY_DOCKERFILE_PATH", mapValue = "Dockerfile.guix" }
          ]
      , domains = [ "dev.myproject.com" ]
      }

-- Define a Nix-based environment (simpler, binary packages)
let myNixDen =
      { name = "experiment"
      , backend = Types.Backend.Nix
      , dockerfile = None Text  -- Will use Dockerfile by default
      , restartPolicy = Some Types.RestartPolicy.Always
      , healthcheck = None Types.Healthcheck
      , ports = [ { port = 22, protocol = Some "tcp" } ]
      , volumes = Defaults.defaultVolumes
      , resources = Some { cpu = Some "1", memory = Some "2Gi" }
      , secrets =
          [ Types.Secret.FromEnv
              { name = "TAILSCALE_AUTHKEY", envVar = "TAILSCALE_AUTHKEY" }
          ]
      , guix = None Types.GuixConfig
      , nix = Some
          { packages =
              Defaults.defaultNixPackages
            # [ { name = "nodejs", version = None Text }
              , { name = "bun", version = None Text }
              ]
          , extraConfig = None Text
          }
      , environment =
          [ { mapKey = "DEN_NAME", mapValue = "den-experiment" }
          , { mapKey = "DEN_BACKEND", mapValue = "nix" }
          ]
      , domains = [] : List Text
      }

-- Choose which configuration to use
in  myGuixDen
