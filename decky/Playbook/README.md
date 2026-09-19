# Playbook (Decky)

QAM **Run post-update** starts `./post-update.sh` after a SteamOS update.
Same steps as `fgpc host post-update`: pacman, Sunshine, Game Mode kms
unit, mux, Decky plugins, official **Tender** zip (then `rom-launcher`
wrap), health-check.

QAM **Update Tender + wrap** is the smaller job: official GitHub
`Tender.zip` when behind, then `ensure-eden-component.sh --wrap-launcher`
so dual-screen / Eden host launches stay on Play. Use this after a Tender
plugin update without running the full post-update. Manual leftover sudo
lines show in the panel.

Install: `scripts/ensure-playbook-decky.sh`. PluginLoader is root —
`main.py` calls `scripts/playbook-post-update.py` as user `deck` (`runuser`
+ session bus + `systemd-run --user`). Never `sudo systemctl --user`.
Never `pgrep -f` sunshine. `~/homebrew/plugins` is often `root:root`; copy
needs sudo, then reload Decky.

The run is oneshot in the background (a few minutes). Reopen QAM to see
ok / warn / fail counts. Do not start a second copy while one is active.
Enter the `deck` sudo password in QAM first so udev / sudoers / plugin
copies can run (password stays in tmpfs askpass, then is wiped). Do not
`sudo ./post-update.sh`. Skip a step with `PLAYBOOK_SKIP=name` or
`SKIP_ENSURE_NAME=1` (Switch 2 is skipped by default). OpenRGB always runs.
