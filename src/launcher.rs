//! Open folders, files/apps and web links using the OS defaults.

use std::path::Path;
use std::process::Command;

use crate::config::expand_user;
use crate::models::{Item, ItemKind};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LaunchError(pub String);

impl std::fmt::Display for LaunchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}
impl std::error::Error for LaunchError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Os {
    Windows,
    MacOs,
    Linux,
}

impl Os {
    pub fn current() -> Os {
        if cfg!(windows) {
            Os::Windows
        } else if cfg!(target_os = "macos") {
            Os::MacOs
        } else {
            Os::Linux
        }
    }
}

/// Builds the command used to open or reveal something. Pure, so it is testable.
pub fn open_command(os: Os, target: &str) -> (String, Vec<String>) {
    match os {
        Os::Windows => ("explorer".into(), vec![target.into()]),
        Os::MacOs => ("open".into(), vec![target.into()]),
        Os::Linux => ("xdg-open".into(), vec![target.into()]),
    }
}

pub fn reveal_command(os: Os, path: &Path) -> (String, Vec<String>) {
    match os {
        Os::Windows => ("explorer".into(), vec![format!("/select,{}", path.display())]),
        Os::MacOs => ("open".into(), vec!["-R".into(), path.display().to_string()]),
        Os::Linux => {
            let folder = if path.is_dir() {
                path.to_path_buf()
            } else {
                path.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new(".")).to_path_buf()
            };
            ("xdg-open".into(), vec![folder.display().to_string()])
        }
    }
}

type Spawn = Box<dyn Fn(&str, &[String]) -> std::io::Result<()>>;

/// Side effects are injectable so the type is easy to test.
pub struct Launcher {
    os: Os,
    spawn: Spawn,
}

impl Default for Launcher {
    fn default() -> Self {
        Self::new()
    }
}

impl Launcher {
    pub fn new() -> Self {
        Self::with_spawn(
            Os::current(),
            Box::new(|prog, args| {
                Command::new(prog).args(args).spawn().map(|mut child| {
                    // Reap the child in the background so it never lingers as a zombie.
                    std::thread::spawn(move || {
                        let _ = child.wait();
                    });
                })
            }),
        )
    }

    pub fn with_spawn(os: Os, spawn: Spawn) -> Self {
        Self { os, spawn }
    }

    pub fn open_item(&self, item: &Item) -> Result<(), LaunchError> {
        match item.kind {
            ItemKind::Url => self.open_url(&item.target),
            ItemKind::Folder => self.open_folder(&item.target),
            ItemKind::File => self.open_file(&item.target),
        }
    }

    pub fn open_url(&self, url: &str) -> Result<(), LaunchError> {
        let (prog, args) = open_command(self.os, url);
        (self.spawn)(&prog, &args).map_err(|_| LaunchError(format!("Could not open link:\n{url}")))
    }

    pub fn open_folder(&self, path: &str) -> Result<(), LaunchError> {
        let p = expand_user(path);
        if !p.is_dir() {
            return Err(LaunchError(format!("Folder not found:\n{}", p.display())));
        }
        self.open_with_os(&p)
    }

    pub fn open_file(&self, path: &str) -> Result<(), LaunchError> {
        let p = expand_user(path);
        if !p.exists() {
            return Err(LaunchError(format!("File not found:\n{}", p.display())));
        }
        self.open_with_os(&p)
    }

    /// Show a file/folder in the system file manager (selected where supported).
    pub fn reveal(&self, path: &str) -> Result<(), LaunchError> {
        let p = expand_user(path);
        if !p.exists() {
            return Err(LaunchError(format!("Not found:\n{}", p.display())));
        }
        let (prog, args) = reveal_command(self.os, &p);
        (self.spawn)(&prog, &args)
            .map_err(|e| LaunchError(format!("Could not open:\n{}\n\n{e}", p.display())))
    }

    fn open_with_os(&self, p: &Path) -> Result<(), LaunchError> {
        let (prog, args) = open_command(self.os, &p.display().to_string());
        (self.spawn)(&prog, &args)
            .map_err(|e| LaunchError(format!("Could not open:\n{}\n\n{e}", p.display())))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    type Calls = Rc<RefCell<Vec<(String, Vec<String>)>>>;

    fn launcher(os: Os, fail: bool) -> (Launcher, Calls) {
        let calls: Calls = Rc::default();
        let c = calls.clone();
        let l = Launcher::with_spawn(
            os,
            Box::new(move |p, a| {
                c.borrow_mut().push((p.to_string(), a.to_vec()));
                if fail { Err(std::io::Error::other("boom")) } else { Ok(()) }
            }),
        );
        (l, calls)
    }

    #[test]
    fn opens_per_platform() {
        let dir = tempfile::tempdir().unwrap();
        let d = dir.path().to_str().unwrap();
        for (os, prog) in [(Os::MacOs, "open"), (Os::Linux, "xdg-open"), (Os::Windows, "explorer")] {
            let (l, calls) = launcher(os, false);
            l.open_folder(d).unwrap();
            assert_eq!(calls.borrow()[0].0, prog);
        }
    }

    #[test]
    fn missing_paths_error_without_spawning() {
        let (l, calls) = launcher(Os::Linux, false);
        assert!(l.open_folder("/definitely/not/here").is_err());
        assert!(l.open_file("/definitely/not/here.txt").is_err());
        assert!(l.reveal("/definitely/not/here").is_err());
        assert!(calls.borrow().is_empty());
    }

    #[test]
    fn url_and_spawn_failure() {
        let (l, calls) = launcher(Os::MacOs, false);
        l.open_url("https://x.org").unwrap();
        assert_eq!(calls.borrow()[0].1, ["https://x.org"]);
        let (l, _) = launcher(Os::MacOs, true);
        assert!(l.open_url("https://x.org").is_err());
    }

    #[test]
    fn reveal_commands() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("a.txt");
        std::fs::write(&f, "x").unwrap();
        assert_eq!(reveal_command(Os::MacOs, &f).1[0], "-R");
        assert!(reveal_command(Os::Windows, &f).1[0].starts_with("/select,"));
        assert_eq!(reveal_command(Os::Linux, &f).1[0], dir.path().display().to_string());
    }
}
