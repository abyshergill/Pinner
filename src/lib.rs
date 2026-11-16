//! Pinner - organise the folders, files, apps and web links you open every day.
//!
//! The library holds everything that is independent of the GUI (data model,
//! SQLite persistence, bookmark import/export, launching, window pinning) so it
//! can be tested without a display.

pub mod bookmarks;
pub mod bootstrap;
pub mod config;
pub mod database;
pub mod dropped;
pub mod launcher;
pub mod models;
pub mod repository;
pub mod window_pinner;

pub const APP_NAME: &str = "Pinner";
