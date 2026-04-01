-- den Dhall Configuration Types
-- Schema for type-safe den environment definitions

let Backend = < Nix | Guix >

let RestartPolicy = < Always | Never | OnFailure >

let Healthcheck =
      { path : Optional Text
      , interval : Optional Text
      , timeout : Optional Text
      , retries : Optional Natural
      }

let Port =
      { port : Natural
      , protocol : Optional Text
      }

let Volume =
      { mount : Text
      , size : Optional Text
      }

let Resource =
      { cpu : Optional Text
      , memory : Optional Text
      }

let Secret =
      < Inline : { name : Text, value : Text }
      | FromFile : { name : Text, path : Text }
      | FromEnv : { name : Text, envVar : Text }
      >

let Package =
      { name : Text
      , version : Optional Text
      }

let Channel =
      { name : Text
      , url : Text
      , branch : Text
      }

let GuixConfig =
      { channels : Optional (List Channel)
      , packages : List Package
      , services : Optional (List Text)
      }

let NixConfig =
      { packages : List Package
      , extraConfig : Optional Text
      }

let DenConfig =
      { name : Text
      , backend : Backend
      , dockerfile : Optional Text
      , restartPolicy : Optional RestartPolicy
      , healthcheck : Optional Healthcheck
      , ports : List Port
      , volumes : List Volume
      , resources : Optional Resource
      , secrets : List Secret
      , guix : Optional GuixConfig
      , nix : Optional NixConfig
      , environment : List { mapKey : Text, mapValue : Text }
      , domains : List Text
      }

in  { Backend
    , RestartPolicy
    , Healthcheck
    , Port
    , Volume
    , Resource
    , Secret
    , Package
    , Channel
    , GuixConfig
    , NixConfig
    , DenConfig
    }
