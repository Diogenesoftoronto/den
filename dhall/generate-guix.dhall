-- Generate Guix files from DenConfig

let Types = ./Types.dhall

let Defaults = ./default.dhall

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

let versionSuffix =
      \(v : Optional Text) -> merge { None = "", Some = \(x : Text) -> "@" ++ x } v

let packageSpec =
      \(p : Types.Package) -> "\"" ++ p.name ++ versionSuffix p.version ++ "\""

let mapPackages =
      \(xs : List Types.Package) ->
        List/fold
          Types.Package
          xs
          (List Text)
          (\(x : Types.Package) -> \(acc : List Text) -> [ packageSpec x ] # acc)
          ([] : List Text)

let channelExpr =
      \(ch : Types.Channel) ->
        "(channel\n"
        ++ "  (name '"
        ++ ch.name
        ++ ")\n"
        ++ "  (url \""
        ++ ch.url
        ++ "\")\n"
        ++ "  (branch \""
        ++ ch.branch
        ++ "\"))"

let mapChannels =
      \(xs : List Types.Channel) ->
        List/fold
          Types.Channel
          xs
          (List Text)
          (\(x : Types.Channel) -> \(acc : List Text) -> [ channelExpr x ] # acc)
          ([] : List Text)

let guixConfigOrDefault =
      \(c : Types.DenConfig) ->
        merge
          { None =
              { channels = [] : List Types.Channel
              , packages = Defaults.defaultGuixPackages
              }
          , Some =
              \(g : Types.GuixConfig) ->
                { channels = merge { None = [] : List Types.Channel, Some = \(xs : List Types.Channel) -> xs } g.channels
                , packages = if isEmpty Types.Package g.packages then Defaults.defaultGuixPackages else g.packages
                }
          }
          c.guix

let generateManifest =
      \(c : Types.DenConfig) ->
        let g = guixConfigOrDefault c

        let pkgLines = concatSep "\n    " (mapPackages g.packages)

        in  ";; Den package manifest for "
            ++ c.name
            ++ "\n"
            ++ ";; Generated from den.dhall\n"
            ++ "(specifications->manifest\n"
            ++ "  '(\n"
            ++ "    "
            ++ pkgLines
            ++ "\n"
            ++ "  ))\n"

let generateChannels =
      \(c : Types.DenConfig) ->
        let g = guixConfigOrDefault c

        let body = if isEmpty Types.Channel g.channels then "%default-channels" else concatSep "\n      " (mapChannels g.channels)

        in  ";; Den channel definitions for "
            ++ c.name
            ++ "\n"
            ++ ";; Generated from den.dhall\n"
            ++ "(cons* "
            ++ body
            ++ "\n"
            ++ "      %default-channels)\n"

let generate =
      \(c : Types.DenConfig) ->
        { manifest = generateManifest c
        , channels = generateChannels c
        }

in  generate
