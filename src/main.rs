//! Pinner - entry point. Run with `cargo run --release`.

mod ui;

use pinner::bootstrap::open_repository;

fn main() {
    let repo = match open_repository(None) {
        Ok(r) => r,
        Err(e) => {
            eprintln!("Pinner could not open its database: {e}");
            std::process::exit(1);
        }
    };
    if let Err(e) = ui::run(repo) {
        eprintln!("Pinner failed: {e}");
        std::process::exit(1);
    }
}
