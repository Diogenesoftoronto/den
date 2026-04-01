# Dhall to Guix: How and Why It Works

## The Problem

Den environments need Guix configuration files — `manifest.scm` for packages and `channels.scm` for channel definitions. These are Guile Scheme files with specific structure. Writing them by hand is error-prone:

- Typos in package names aren't caught until `guix` runs
- Channel definitions require matching names, URLs, and branches — easy to get wrong
- There's no schema validation; a missing paren crashes at runtime
- When the same config drives multiple outputs (Guix manifests, Railway TOML, Dockerfiles), keeping them in sync by hand is a losing game

We want **one source of truth** with **compile-time guarantees**.

## Why Not `dhall-to-guix`?

The first instinct is to look for a `dhall-to-guix` tool analogous to `dhall-to-nix`, `dhall-to-json`, or `dhall-to-yaml`. These exist as part of [dhall-haskell](https://github.com/dhall-lang/dhall-haskell) and are listed on [awesome-dhall](https://github.com/dhall-lang/awesome-dhall).

**There is no `dhall-to-guix`.** The complete list of output format tools from awesome-dhall:

| Tool | Target |
|------|--------|
| `dhall-json` | JSON |
| `dhall-yaml` | YAML |
| `dhall-nix` | Nix expressions |
| `dhall-bash` | Bash variables |
| `dhall-toml` | TOML |
| `dhall-csv` | CSV |

No Guile Scheme target exists. This makes sense — Guix's Scheme is not a generic data format but a full programming language with domain-specific forms like `(specifications->manifest ...)` and `(channel ...)`. A generic serializer can't produce these; you need to know the target API.

## The Key Insight: Dhall Has Text Templating

Dhall is not just a configuration language — it's a **typed text generation language**. Every Dhall expression can be normalized to a `Text` value using `dhall text`. This means Dhall can generate *any* textual output format, including Guile Scheme, as long as you write functions that produce the right strings.

This is the same approach used by projects like [dhall-dot](https://github.com/Gabriel439/dhall-dot) (generates GraphViz DOT) and [dhall-containerfile](https://github.com/softwarefactory-project/dhall-containerfile) (generates Dockerfiles). Neither DOT nor Dockerfile has a dedicated `dhall-to-X` tool — they use Dhall's text concatenation.

The tradeoff vs. a dedicated tool like `dhall-to-nix`:

| | Dedicated tool (`dhall-to-nix`) | Text templating (our approach) |
|---|---|---|
| **Output correctness** | Guaranteed structurally valid | You must get the template right |
| **Type safety of input** | Full | Full (same Dhall types) |
| **Flexibility** | Limited to what the tool supports | Can generate any Scheme form |
| **Maintenance** | Depends on upstream | Self-contained |

We get full type safety on the *input* side (Dhall catches bad configs at compile time) and flexibility on the *output* side (we can generate exactly the Scheme that Guix expects).

## Architecture

```
┌─────────────────────┐
│   example.dhall     │  ← User writes this (type-checked config)
│   (DenConfig)       │
└────────┬────────────┘
         │
         │  applied to
         ▼
┌─────────────────────┐     ┌──────────────┐
│ generate-guix.dhall │────▶│ manifest.scm │  (Guix package manifest)
│ (DenConfig → {..})  │────▶│ channels.scm │  (Guix channel definitions)
└─────────────────────┘     └──────────────┘
         │
         │  also
         ▼
┌──────────────────────┐    ┌──────────────┐
│generate-railway.dhall│───▶│ railway.toml │  (Railway deployment config)
└──────────────────────┘    └──────────────┘
```

One `DenConfig` record feeds multiple generators. Each generator is a Dhall function of type `DenConfig → Text` (or `DenConfig → { manifest : Text, channels : Text }`).

## Walkthrough: How `generate-guix.dhall` Works

### Step 1: Define the Types

Everything starts with `Types.dhall`. The key types for Guix generation:

```dhall
-- A package to install via Guix
let Package =
      { name : Text
      , version : Optional Text
      }

-- A Guix channel (package repository)
let Channel =
      { name : Text
      , url : Text
      , branch : Text
      }

-- The Guix-specific section of a den config
let GuixConfig =
      { channels : Optional (List Channel)
      , packages : List Package
      , services : Optional (List Text)
      }
```

`Channel` is a record, not a plain string. This is important — early versions used `List Text` for channels, which meant the generator had to hardcode URLs. A channel named `"nonguix"` got the wrong URL because the generator couldn't know where nonguix actually lives. Structured records solve this.

### Step 2: Build Helper Functions

Dhall has no standard library for string joining, so `generate-guix.dhall` defines its own:

```dhall
-- Join a list of strings with a separator
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
```

This uses `List/fold` (Dhall's only way to iterate over lists) with an accumulator that tracks whether we're on the first element to avoid a leading separator.

```dhall
-- Check if a list is empty
let isEmpty =
      \(a : Type) ->
      \(xs : List a) ->
        List/fold a xs Bool (\(_ : a) -> \(_ : Bool) -> False) True
```

Dhall has no `List/null` or `List/length`, so we fold: if we ever enter the fold body, the list isn't empty.

### Step 3: Convert Records to Scheme Text

Each Guix concept gets a function that turns a Dhall record into the corresponding Scheme expression as a `Text` value:

**Package specs** — Guix manifests use string package names, optionally with `@version`:

```dhall
let versionSuffix =
      \(v : Optional Text) ->
        merge { None = "", Some = \(x : Text) -> "@" ++ x } v

let packageSpec =
      \(p : Types.Package) ->
        "\"" ++ p.name ++ versionSuffix p.version ++ "\""
```

Given `{ name = "python", version = Some "3.11" }`, this produces `"python@3.11"`.
Given `{ name = "git", version = None Text }`, this produces `"git"`.

**Channel expressions** — each channel becomes a `(channel ...)` S-expression:

```dhall
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
```

This produces:

```scheme
(channel
  (name 'nonguix)
  (url "https://gitlab.com/nonguix/nonguix.git")
  (branch "master"))
```

### Step 4: Compose Into Full Documents

The `generateManifest` function assembles the full `manifest.scm`:

```dhall
let generateManifest =
      \(c : Types.DenConfig) ->
        let g = guixConfigOrDefault c
        let pkgLines = concatSep "\n    " (mapPackages g.packages)
        in  ";; Den package manifest for " ++ c.name ++ "\n"
            ++ ";; Generated from den.dhall\n"
            ++ "(specifications->manifest\n"
            ++ "  '(\n"
            ++ "    " ++ pkgLines ++ "\n"
            ++ "  ))\n"
```

The `guixConfigOrDefault` function handles the case where no `guix` section is provided, falling back to default packages:

```dhall
let guixConfigOrDefault =
      \(c : Types.DenConfig) ->
        merge
          { None =
              { channels = [] : List Types.Channel
              , packages = Defaults.defaultGuixPackages
              }
          , Some =
              \(g : Types.GuixConfig) ->
                { channels = merge { None = [] : List Types.Channel
                                   , Some = \(xs : List Types.Channel) -> xs
                                   } g.channels
                , packages = if isEmpty Types.Package g.packages
                             then Defaults.defaultGuixPackages
                             else g.packages
                }
          }
          c.guix
```

The `merge` keyword is Dhall's pattern matching — it handles `Optional` (like Haskell's `Maybe`) and union types (like Haskell's sum types / Rust's enums).

### Step 5: Export the Generator

The final export is a function that takes a `DenConfig` and returns both files:

```dhall
let generate =
      \(c : Types.DenConfig) ->
        { manifest = generateManifest c
        , channels = generateChannels c
        }

in  generate
```

## Running It

### Type-check only (catches errors without generating output)

```bash
dhall type --file dhall/example.dhall
```

### Generate manifest.scm

```bash
dhall text <<< '(./dhall/generate-guix.dhall (./dhall/example.dhall)).manifest'
```

Output:

```scheme
;; Den package manifest for myproject
;; Generated from den.dhall
(specifications->manifest
  '(
    "fish"
    "git"
    "helix"
    "zellij"
    "jj"
    "gh"
    "fzf"
    "ripgrep"
    "fd"
    "bat"
    "python"
    "node"
    "rust"
    "go"
  ))
```

### Generate channels.scm

```bash
dhall text <<< '(./dhall/generate-guix.dhall (./dhall/example.dhall)).channels'
```

Output:

```scheme
;; Den channel definitions for myproject
;; Generated from den.dhall
(cons* (channel
  (name 'guix)
  (url "https://git.savannah.gnu.org/git/guix.git")
  (branch "master"))
      (channel
  (name 'nonguix)
  (url "https://gitlab.com/nonguix/nonguix.git")
  (branch "master"))
      (channel
  (name 'tailscale)
  (url "https://github.com/tailscale/guix.git")
  (branch "main"))
      %default-channels)
```

### Generate everything at once

```bash
./scripts/generate-from-dhall.sh dhall/example.dhall /tmp/output
```

This validates the Dhall, detects the backend, and writes `manifest.scm`, `channels.scm`, and `railway.toml`.

## What Dhall Catches at Compile Time

Dhall's type system prevents entire classes of errors before any Scheme is generated:

**Wrong field name:**

```dhall
{ naem = "git", version = None Text }
--  ^ typo: "naem" instead of "name"
```

```
Error: Expression doesn't match annotation
```

**Wrong type for a field:**

```dhall
{ name = "git", version = 42 }
--                         ^ Natural, not Optional Text
```

```
Error: Expression doesn't match annotation
```

**Missing required field:**

```dhall
{ name = "myproject"
, backend = Types.Backend.Guix
-- forgot ports, volumes, etc.
}
```

```
Error: Expression doesn't match annotation
```

**Invalid union variant:**

```dhall
Types.Backend.Docker
--            ^ doesn't exist; only Nix | Guix
```

```
Error: <Docker> is not a constructor of < Guix | Nix >
```

None of these errors are possible with hand-written Scheme files. You'd only discover them when `guix` tries to evaluate the file and fails with a Scheme error.

## File Map

```
dhall/
├── Types.dhall           # All type definitions (DenConfig, Package, Channel, etc.)
├── default.dhall         # Default values (packages, ports, volumes)
├── example.dhall         # Example DenConfig showing both Guix and Nix backends
├── generate-guix.dhall   # DenConfig → { manifest : Text, channels : Text }
└── generate-railway.dhall # DenConfig → Text (railway.toml)

scripts/
└── generate-from-dhall.sh # Shell wrapper: validate + detect backend + generate all files
```

## Adding a New Guix Output

Say you want to generate a `guix.scm` build file (not just a manifest). The pattern is:

1. Write the target Scheme by hand first to know what you're generating
2. Create a new Dhall function `generateBuild : DenConfig → Text`
3. Use string concatenation to assemble the Scheme, pulling values from the typed config
4. Add a new field to the `generate` return record
5. Update `generate-from-dhall.sh` to extract and write it

The type system ensures that any config field you access actually exists and has the right type. The text templating ensures you can generate any Scheme form Guix needs.
