# Packaging

## systemd user service

`packaging/systemd/user/shuvagent.service` runs `shuvagent run` as a user
service and leaves the control socket under the normal user runtime directory.

Install after placing the `shuvagent` executable on the user service `PATH`:

```bash
mkdir -p ~/.config/systemd/user
cp packaging/systemd/user/shuvagent.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now shuvagent.service
```

Useful commands:

```bash
systemctl --user status shuvagent.service
systemctl --user restart shuvagent.service
systemctl --user stop shuvagent.service
journalctl --user -u shuvagent.service -f
```

Verify the unit file from the repo:

```bash
systemd-analyze verify --user packaging/systemd/user/shuvagent.service
```
