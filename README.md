# DSH SSH GPU monitor

A DSH plugin that adds a live GPU monitoring tab to [dsh-better-sidebar](https://www.npmjs.com/package/dsh-better-sidebar).

It shows GPU utilization, memory, temperature, power, clocks, per-GPU mini trends, process ownership, GPU assignment, runtime, host load, and disk usage. Data refreshes every five seconds.

## Requirements

- DSH 0.2.2-rc.1 or newer
- `dsh-better-sidebar` 0.30.x
- Python 3.9+ on the DSH host
- `paramiko` (`python -m pip install paramiko`)
- An SSH server with `nvidia-smi`, `ps`, `uptime`, `free`, and `df`

## Install from npm

```bash
dsh plugin --profile desktop add dsh-ssh-gpu-monitor
```

Then hard-refresh the DSH page and open **GPU 监控** from the right sidebar's `+` menu.

## Configure SSH

Open the GPU 监控 tab. On first use it shows a configuration form for host, port, username, and password. Credentials are held by the running Host process and are not committed or shown in the UI after submission.

For headless/local setup, copy the template beside the bundled connector:

```bash
cp ssh/.env.example ssh/.env
```

Set `SSH_HOST`, `SSH_PORT`, `SSH_USER`, and `SSH_PASSWORD` in `ssh/.env`. The `.env` file is intentionally ignored by Git and must never be committed. For an installed package, copy `ssh/.env.example` to the package's `ssh/.env`, or set `DSH_GPU_MONITOR_ROOT` to a separate directory containing `ssh/.env` if the profile cannot discover it automatically. On Windows, the installed package is usually under `%USERPROFILE%\\.dsh\\profiles\\<profile>\\node_modules\\dsh-ssh-gpu-monitor\\ssh\\.env`.

> Password authentication is supported for compatibility. For production deployments, prefer an SSH key and a dedicated read-only monitoring account. The plugin only executes read-only commands.

## Development

```bash
node --check index.js
node --check client.js
```

The package is a plain JavaScript DSH bundle; no build step is required. Install the local directory with the DSH plugin manager when testing changes.

## Security

The plugin does not bundle credentials. Never commit `ssh/.env`, private keys, or server output containing secrets. SSH host-key checking currently follows the bundled connector's compatibility behavior; review and harden it before use in a security-sensitive environment.

## License

MIT
