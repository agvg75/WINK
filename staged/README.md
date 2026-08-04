# Vidal-Gadea Lab Tools

Development follows
`docs/development/CROSS_TOOL_PROPAGATION_POLICY.md`: every useful feature or
failure fix triggers an applicability audit across NIKE, with conditional reuse
and an explicit scientific-metric firewall.

Students should start with:

`Launch_Lab_Hub.bat`

Run `Setup_Lab_Tools.bat` once on each lab computer before first use. It needs
Administrator rights, because it builds one shared Python environment under
`%ProgramData%` that every user of that computer can share.

**If that fails with "access is denied"**, run `Setup_Lab_Tools_ThisUser.bat`
instead. It builds a private environment under your own profile and needs no
Administrator rights. Only you will be able to use it, so on a shared lab
computer prefer the Administrator route.

Either way, if you see "No Python found", install Python 3 from
<https://www.python.org/downloads/> first and tick **Add python.exe to PATH** on
the first screen.

There is no bundled `.exe`: WINK is Python plus a launcher, so on a computer
that has never been set up there is nothing to run yet. That is expected.

This staged layout keeps the student-facing launch point at the root while
placing implementations under `tools`, the hub under `app`, Fiji integration
under `fiji`, and validation material under `tests`.

Development diagnostic:

```text
python app\diagnostics.py
```
