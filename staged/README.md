# Vidal-Gadea Lab Tools

Development follows
`docs/development/CROSS_TOOL_PROPAGATION_POLICY.md`: every useful feature or
failure fix triggers an applicability audit across NIKE, with conditional reuse
and an explicit scientific-metric firewall.

Students should start with:

`Launch_Lab_Hub.bat`

Run `Setup_Lab_Tools.bat` once on each lab computer before first use.

This staged layout keeps the student-facing launch point at the root while
placing implementations under `tools`, the hub under `app`, Fiji integration
under `fiji`, and validation material under `tests`.

Development diagnostic:

```text
python app\diagnostics.py
```
