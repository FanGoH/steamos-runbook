# Playbook (Decky)

QAM button to run `./post-update.sh` after a SteamOS update. Same steps as
`fgpc host post-update`: pacman, Sunshine, Game Mode kms unit, mux, Decky
plugins, official **Tender** zip (then `rom-launcher` wrap), health-check.
Manual leftover sudo lines show in the panel.

Install: `scripts/ensure-playbook-decky.sh`. PluginLoader is root —
`main.py` calls `scripts/playbook-post-update.py` as user `deck` (`runuser`
+ session bus + `systemd-run --user`). Never `sudo systemctl --user`.
Never `pgrep -f` sunshine. `~/homebrew/plugins` is often `root:root`; copy
needs sudo, then reload Decky.

The run is oneshot in the background (a few minutes). Reopen QAM to see
ok / warn / fail counts. Do not start a second copy while one is active.
