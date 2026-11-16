//! Look and feel: rounded corners, roomy spacing and one accent colour (light and dark).

use eframe::egui::{self, Color32, FontId, Rounding, Stroke, TextStyle};

use super::icons::ACCENT;

pub fn apply(ctx: &egui::Context) {
    ctx.all_styles_mut(|style| {
        style.spacing.item_spacing = egui::vec2(8.0, 7.0);
        style.spacing.button_padding = egui::vec2(12.0, 6.0);
        style.spacing.interact_size.y = 28.0;
        style.spacing.window_margin = egui::Margin::same(16.0);
        style.spacing.indent = 18.0;

        let text = &mut style.text_styles;
        text.insert(TextStyle::Heading, FontId::proportional(22.0));
        text.insert(TextStyle::Body, FontId::proportional(14.5));
        text.insert(TextStyle::Button, FontId::proportional(14.0));
        text.insert(TextStyle::Small, FontId::proportional(12.0));

        let v = &mut style.visuals;
        let r = Rounding::same(8.0);
        v.widgets.noninteractive.rounding = r;
        v.widgets.inactive.rounding = r;
        v.widgets.hovered.rounding = r;
        v.widgets.active.rounding = r;
        v.widgets.open.rounding = r;
        v.window_rounding = Rounding::same(14.0);
        v.menu_rounding = Rounding::same(10.0);
        v.selection.bg_fill = ACCENT.linear_multiply(0.35);
        v.selection.stroke = Stroke::new(1.0_f32, ACCENT);
        v.hyperlink_color = ACCENT;
        v.widgets.hovered.bg_stroke = Stroke::new(1.0_f32, ACCENT.linear_multiply(0.7));
        v.window_shadow.blur = 24.0;
        v.popup_shadow.blur = 16.0;
        if v.dark_mode {
            v.panel_fill = Color32::from_rgb(24, 25, 31);
            v.extreme_bg_color = Color32::from_rgb(17, 18, 23);
            v.faint_bg_color = Color32::from_rgb(33, 35, 43);
            v.window_fill = Color32::from_rgb(30, 32, 40);
            v.widgets.inactive.weak_bg_fill = Color32::from_rgb(44, 47, 58);
            v.widgets.hovered.weak_bg_fill = Color32::from_rgb(56, 60, 74);
        } else {
            v.panel_fill = Color32::from_rgb(244, 246, 250);
            v.extreme_bg_color = Color32::WHITE;
            v.faint_bg_color = Color32::from_rgb(255, 255, 255);
            v.window_fill = Color32::WHITE;
            v.widgets.inactive.weak_bg_fill = Color32::from_rgb(230, 234, 242);
            v.widgets.hovered.weak_bg_fill = Color32::from_rgb(216, 224, 240);
        }
    });
}
