-- Generate Railway TOML from DenConfig

let Types = ./Types.dhall

let concatSep =
      \(sep : Text) ->
      \(xs : List Text) ->
        ( List/fold
            Text
            xs
            { out : Text, first : Bool }
            ( \(x : Text) ->
              \(acc : { out : Text, first : Bool }) ->
                { out = if acc.first then x else x ++ sep ++ acc.out
                , first = False
                }
            )
            { out = "", first = True }
        ).out

let isEmpty =
      \(a : Type) ->
      \(xs : List a) ->
        List/fold a xs Bool (\(_ : a) -> \(_ : Bool) -> False) True

let backendToText =
      \(b : Types.Backend) -> merge { Nix = "nix", Guix = "guix" } b

let restartPolicyToText =
      \(r : Types.RestartPolicy) ->
        merge { Always = "ALWAYS", Never = "NEVER", OnFailure = "ON_FAILURE" } r

let envLine =
      \(e : { mapKey : Text, mapValue : Text }) ->
        e.mapKey ++ " = \"" ++ e.mapValue ++ "\""

let secretLine =
      \(s : Types.Secret) ->
        merge
          { Inline = \(x : { name : Text, value : Text }) -> x.name ++ " = \"" ++ x.value ++ "\""
          , FromFile = \(x : { name : Text, path : Text }) -> x.name ++ " = \"" ++ x.path ++ "\""
          , FromEnv = \(x : { name : Text, envVar : Text }) -> x.name ++ " = \"" ++ x.envVar ++ "\""
          }
          s

let volumeBlock =
      \(v : Types.Volume) ->
        "[[deploy.volumes]]\n"
        ++ "mount_path = \""
        ++ v.mount
        ++ "\"\n"
        ++ "size = \""
        ++ (merge { None = "10Gi", Some = \(s : Text) -> s } v.size)
        ++ "\""

let resourceSection =
      \(r : Optional Types.Resource) ->
        merge
          { None = ""
          , Some =
              \(x : Types.Resource) ->
                let cpuLine = merge { None = "", Some = \(v : Text) -> "cpu = \"" ++ v ++ "\"" } x.cpu
                let memoryLine = merge { None = "", Some = \(v : Text) -> "memory = \"" ++ v ++ "\"" } x.memory
                in  concatSep "\n" [ cpuLine, memoryLine ]
          }
          r

let envLines =
      \(xs : List { mapKey : Text, mapValue : Text }) ->
        List/fold
          { mapKey : Text, mapValue : Text }
          xs
          (List Text)
          (\(x : { mapKey : Text, mapValue : Text }) -> \(acc : List Text) -> [ envLine x ] # acc)
          ([] : List Text)

let secretLines =
      \(xs : List Types.Secret) ->
        List/fold
          Types.Secret
          xs
          (List Text)
          (\(x : Types.Secret) -> \(acc : List Text) -> [ secretLine x ] # acc)
          ([] : List Text)

let volumeLines =
      \(xs : List Types.Volume) ->
        List/fold
          Types.Volume
          xs
          (List Text)
          (\(x : Types.Volume) -> \(acc : List Text) -> [ volumeBlock x ] # acc)
          ([] : List Text)

let domainLines =
      \(xs : List Text) ->
        List/fold
          Text
          xs
          (List Text)
          (\(d : Text) -> \(acc : List Text) -> [ "[[deploy.domains]]\ndomain = \"" ++ d ++ "\"" ] # acc)
          ([] : List Text)

let generate =
      \(config : Types.DenConfig) ->
        let defaultDockerfile = merge { Nix = "Dockerfile", Guix = "Dockerfile.guix" } config.backend

        let dockerfilePath =
              merge { None = defaultDockerfile, Some = \(x : Text) -> x } config.dockerfile

        let restartPolicy =
              merge
                { None = "ALWAYS", Some = \(x : Types.RestartPolicy) -> restartPolicyToText x }
                config.restartPolicy

        let healthcheckLine =
              merge
                { None = "# healthcheckPath not set"
                , Some =
                    \(h : Types.Healthcheck) ->
                      merge
                        { None = "# healthcheckPath not set"
                        , Some = \(p : Text) -> "healthcheckPath = \"" ++ p ++ "\""
                        }
                        h.path
                }
                config.healthcheck

        let allEnvLines = envLines config.environment # secretLines config.secrets
        let hasEnv = if isEmpty Text allEnvLines then False else True
        let hasVolumes = if isEmpty Types.Volume config.volumes then False else True

        let envSection = if hasEnv then "[deploy.env]\n" ++ concatSep "\n" allEnvLines else ""

        let volumeSection = if hasVolumes then concatSep "\n" (volumeLines config.volumes) else ""

        let domainSection =
              if isEmpty Text config.domains then "" else concatSep "\n" (domainLines config.domains)

        let resources = resourceSection config.resources
        let hasResources = merge { None = False, Some = \(x : Types.Resource) -> True } config.resources

        in  "# Generated from den.dhall\n"
            ++ "# Backend: "
            ++ backendToText config.backend
            ++ "\n"
            ++ "# Name: "
            ++ config.name
            ++ "\n\n"
            ++ "[build]\n"
            ++ "dockerfilePath = \""
            ++ dockerfilePath
            ++ "\"\n\n"
            ++ "[deploy]\n"
            ++ "restartPolicyType = \""
            ++ restartPolicy
            ++ "\"\n"
            ++ healthcheckLine
            ++ "\n\n"
            ++ envSection
            ++ (if hasEnv then "\n\n" else "")
            ++ volumeSection
            ++ (if hasVolumes then "\n\n" else "")
            ++ resources
            ++ (if hasResources then "\n\n" else "")
            ++ domainSection
            ++ "\n"

in  generate
