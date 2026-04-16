pub mod assets {
    use anyhow::{bail, Context, Result};
    use std::fs;
    use std::path::{Path, PathBuf};

    #[derive(Debug, Clone, PartialEq, Eq)]
    pub struct AssetDirs {
        pub root: PathBuf,
        pub dhall_dir: PathBuf,
        pub scripts_dir: PathBuf,
        pub guix_dir: PathBuf,
    }

    struct EmbeddedFile {
        relative_path: &'static str,
        contents: &'static str,
        executable: bool,
    }

    const EMBEDDED_FILES: &[EmbeddedFile] = &[
        EmbeddedFile {
            relative_path: "dhall/Types.dhall",
            contents: include_str!("../../../dhall/Types.dhall"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "dhall/default.dhall",
            contents: include_str!("../../../dhall/default.dhall"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "dhall/example.dhall",
            contents: include_str!("../../../dhall/example.dhall"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "dhall/generate-guix.dhall",
            contents: include_str!("../../../dhall/generate-guix.dhall"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "dhall/generate-railway.dhall",
            contents: include_str!("../../../dhall/generate-railway.dhall"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "guix/channels.scm",
            contents: include_str!("../../../guix/channels.scm"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "guix/home.scm",
            contents: include_str!("../../../guix/home.scm"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "guix/manifest.scm",
            contents: include_str!("../../../guix/manifest.scm"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "guix/system.scm",
            contents: include_str!("../../../guix/system.scm"),
            executable: false,
        },
        EmbeddedFile {
            relative_path: "scripts/bootstrap-guix.sh",
            contents: include_str!("../../../scripts/bootstrap-guix.sh"),
            executable: true,
        },
        EmbeddedFile {
            relative_path: "scripts/bootstrap.sh",
            contents: include_str!("../../../scripts/bootstrap.sh"),
            executable: true,
        },
        EmbeddedFile {
            relative_path: "scripts/build-guix-image.sh",
            contents: include_str!("../../../scripts/build-guix-image.sh"),
            executable: true,
        },
        EmbeddedFile {
            relative_path: "scripts/entrypoint-guix.sh",
            contents: include_str!("../../../scripts/entrypoint-guix.sh"),
            executable: true,
        },
        EmbeddedFile {
            relative_path: "scripts/entrypoint.sh",
            contents: include_str!("../../../scripts/entrypoint.sh"),
            executable: true,
        },
        EmbeddedFile {
            relative_path: "scripts/generate-from-dhall.sh",
            contents: include_str!("../../../scripts/generate-from-dhall.sh"),
            executable: true,
        },
        EmbeddedFile {
            relative_path: "scripts/install-hooks.sh",
            contents: include_str!("../../../scripts/install-hooks.sh"),
            executable: true,
        },
    ];

    fn asset_dirs(root: PathBuf) -> AssetDirs {
        AssetDirs {
            dhall_dir: root.join("dhall"),
            scripts_dir: root.join("scripts"),
            guix_dir: root.join("guix"),
            root,
        }
    }

    fn is_asset_root(root: &Path) -> bool {
        root.join("dhall").join("Types.dhall").is_file()
            && root
                .join("scripts")
                .join("generate-from-dhall.sh")
                .is_file()
            && root.join("guix").join("manifest.scm").is_file()
    }

    fn ensure_materialized(root: &Path) -> Result<()> {
        for file in EMBEDDED_FILES {
            let path = root.join(file.relative_path);
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)
                    .with_context(|| format!("failed to create {}", parent.display()))?;
            }
            let should_write = match fs::read_to_string(&path) {
                Ok(existing) => existing != file.contents,
                Err(_) => true,
            };
            if should_write {
                fs::write(&path, file.contents)
                    .with_context(|| format!("failed to write {}", path.display()))?;
            }

            #[cfg(unix)]
            if file.executable {
                use std::os::unix::fs::PermissionsExt;
                let mut perms = fs::metadata(&path)?.permissions();
                perms.set_mode(0o755);
                fs::set_permissions(&path, perms)?;
            }
        }
        Ok(())
    }

    fn candidate_roots() -> Vec<PathBuf> {
        let mut roots = Vec::new();

        if let Ok(explicit) = std::env::var("DEN_ASSET_ROOT") {
            let explicit = PathBuf::from(explicit);
            if !explicit.as_os_str().is_empty() {
                roots.push(explicit);
            }
        }

        if let Ok(cwd) = std::env::current_dir() {
            for ancestor in cwd.ancestors() {
                roots.push(ancestor.to_path_buf());
            }
        }

        if let Ok(exe) = std::env::current_exe() {
            for ancestor in exe.ancestors() {
                roots.push(ancestor.to_path_buf());
            }
        }

        if let Ok(home) = std::env::var("HOME") {
            roots.push(PathBuf::from(home).join("Projects").join("den"));
        }

        roots
    }

    fn cache_root() -> PathBuf {
        if let Ok(path) = std::env::var("DEN_ASSET_CACHE_DIR") {
            return PathBuf::from(path);
        }
        if let Ok(home) = std::env::var("HOME") {
            return PathBuf::from(home)
                .join(".local")
                .join("share")
                .join("den")
                .join("assets");
        }
        std::env::temp_dir().join("den-assets")
    }

    pub fn locate_or_materialize_assets() -> Result<AssetDirs> {
        for root in candidate_roots() {
            if is_asset_root(&root) {
                return Ok(asset_dirs(root));
            }
        }

        let cache = cache_root();
        fs::create_dir_all(&cache)
            .with_context(|| format!("failed to create {}", cache.display()))?;
        ensure_materialized(&cache)?;
        if !is_asset_root(&cache) {
            bail!("failed to materialize den assets into {}", cache.display());
        }
        Ok(asset_dirs(cache))
    }

    pub fn materialize_assets_into(root: &Path) -> Result<AssetDirs> {
        fs::create_dir_all(root).with_context(|| format!("failed to create {}", root.display()))?;
        ensure_materialized(root)?;
        if !is_asset_root(root) {
            bail!("failed to materialize den assets into {}", root.display());
        }
        Ok(asset_dirs(root.to_path_buf()))
    }
}
