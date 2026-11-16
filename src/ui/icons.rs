//! SVG icons (embedded from `assets/icons`) and small helpers to draw them.

use eframe::egui::{self, Color32, Image, ImageSource, Vec2};

pub const ACCENT: Color32 = Color32::from_rgb(91, 141, 239);

fn source(name: &str) -> ImageSource<'static> {
    macro_rules! icons {
        ($($n:literal),* $(,)?) => {
            match name {
                $($n => egui::include_image!(concat!(env!("CARGO_MANIFEST_DIR"), "/assets/icons/", $n, ".svg")),)*
                _ => egui::include_image!(concat!(env!("CARGO_MANIFEST_DIR"), "/assets/icons/file.svg")),
            }
        };
    }
    icons!(
        "app", "folder", "file", "url", "group_paths", "group_browser", "window_pin", "plus", "play",
        "import", "export", "refresh", "search", "star", "close", "trash", "folder_plus", "github",
    )
}

/// A coloured icon at `size` points.
pub fn image(name: &str, size: f32) -> Image<'static> {
    Image::new(source(name)).fit_to_exact_size(Vec2::splat(size))
}

/// A monochrome icon tinted to the current text colour.
pub fn mono(ui: &egui::Ui, name: &str, size: f32) -> Image<'static> {
    image(name, size).tint(ui.visuals().text_color())
}

/// A button with a monochrome icon in front of its label.
pub fn button(ui: &egui::Ui, name: &str, text: &str) -> egui::Button<'static> {
    egui::Button::image_and_text(mono(ui, name, 15.0), text.to_string())
}

/// The accent-coloured call-to-action button.
pub fn primary_button(name: &str, text: &str) -> egui::Button<'static> {
    egui::Button::image_and_text(image(name, 14.0).tint(Color32::WHITE), egui::RichText::new(text).color(Color32::WHITE))
        .fill(ACCENT)
}
