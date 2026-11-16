//! Runtime configuration (storage locations).

use std::path::PathBuf;

pub const DB_ENV_VAR: &str = "PINNER_DB";
pub const DB_FILE_NAME: &str = "pinner.db";

/// Expand a leading `~` to the user's home directory.
pub fn expand_user(path: &str) -> PathBuf {
    if path == "~" || path.starts_with("~/") || path.starts_with("~\\") {
        if let Some(home) = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")) {
            let rest = path[1..].trim_start_matches(['/', '\\']);
            return PathBuf::from(home).join(rest);
        }
    }
    PathBuf::from(path)
}

/// Where the SQLite database lives: `pinner.db` next to the executable
/// (or in the current directory when run through `cargo run`).
/// Override with the `PINNER_DB` environment variable.
pub fn default_db_path() -> PathBuf {
    if let Some(over) = std::env::var_os(DB_ENV_VAR).filter(|v| !v.is_empty()) {
        return expand_user(&over.to_string_lossy());
    }
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));
    match exe_dir {
        // Running from a cargo `target` directory: keep the database in the project folder.
        Some(d) if d.components().any(|c| c.as_os_str() == "target") => {
            std::env::current_dir().unwrap_or_default().join(DB_FILE_NAME)
        }
        Some(d) => d.join(DB_FILE_NAME),
        None => PathBuf::from(DB_FILE_NAME),
    }
}
