//! The 'About' tab: what Pinner is, its version and where to find the project.

use eframe::egui::{self, RichText};

use super::icons;

pub const GITHUB_PROFILE: &str = "https://github.com/abyshergill";
pub const GITHUB_REPO: &str = "https://github.com/abyshergill/Pinner";

/// Draws the tab; returns a link the app should open, if one was clicked.
pub fn ui(ui: &mut egui::Ui) -> Option<&'static str> {
    let mut open = None;
    ui.add_space(24.0);
    ui.vertical_centered(|ui| {
        ui.add(icons::image("app", 84.0));
        ui.add_space(8.0);
        ui.label(RichText::new(pinner::APP_NAME).heading().size(30.0));
        ui.weak(format!("Version {}", env!("CARGO_PKG_VERSION")));
        ui.add_space(12.0);
        ui.add(
            egui::Label::new("Organise the folders, files, apps and web links you open every day - grouped in your own folders, stored locally in SQLite.")
                .wrap(),
        );
        ui.add_space(18.0);
        ui.label(RichText::new("Made by abyshergill").strong());
        ui.add_space(8.0);
        ui.horizontal(|ui| {
            ui.add_space((ui.available_width() - 330.0).max(0.0) / 2.0);
            let profile = egui::Button::image_and_text(
                icons::image("github", 16.0).tint(egui::Color32::WHITE),
                RichText::new("GitHub profile").color(egui::Color32::WHITE),
            )
            .fill(icons::ACCENT);
            if ui.add(profile).on_hover_text(GITHUB_PROFILE).clicked() {
                open = Some(GITHUB_PROFILE);
            }
            if ui.add(icons::button(ui, "github", "Project repository")).on_hover_text(GITHUB_REPO).clicked() {
                open = Some(GITHUB_REPO);
            }
        });
        ui.add_space(16.0);
        ui.weak("Open source under the MIT license. Issues and pull requests are welcome.");
    });
    open
}
