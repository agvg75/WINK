# Tierpsy external tool setup

Status on 2026-07-20:

- Docker Desktop 29.6.1 is installed, but the Docker engine was not running
  during verification.
- VcXsrv 21.1.16.1 is installed.
- The official `tierpsy/tierpsy-tracker` image has not yet been pulled or
  launch-tested. Do not describe this setup as runnable until those checks pass.
- Source repositories are stored at
  `L:\10_AGVG LAB\Lab Tools\External Tools\Tierpsy`.

Pinned source revisions:

- `Tierpsy/tierpsy-tracker` development:
  `2653ecb3697602e3d6d763c92bc5fb1864c60f15`
- `Tierpsy/tierpsy-tools-python`:
  `59210e0b7b0b33a68bed73e104c960ee136dc764`
- `aexbrown/Behavioural_Syntax`:
  `6c8518c63853f8c94f0cfa144848cfe83d09ed1a`

## Finish and verify on this workstation

1. Start Docker Desktop interactively and complete any first-run agreement,
   WSL 2, virtualization, sign-out, or restart prompt.
2. Wait until Docker Desktop reports that the engine is running.
3. Open PowerShell and run `docker info`.
4. Run `docker pull tierpsy/tierpsy-tracker`.
5. Start VcXsrv/XLaunch and permit the private-network firewall rule if
   Windows asks.
6. Run `Start_Tierpsy.ps1 -DataPath "C:\path\to\worm\data"`.
7. Confirm the Tierpsy graphical interface opens and can see the selected data
   folder as `/DATA/local_drive`.

The NIKE validation stamp, plate-as-replicate rules, Capability Gate, and
Failure Library do not automatically attach to Tierpsy-native outputs.

