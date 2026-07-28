# NIKE Lab Tools v11.72

## Track one worm — reviewed segmentation now yields spines on thin / burrowing worms

**Problem.** The DIC worm tracker was designed for crawling on a bacterial lawn,
where the worm is the only *thick* object and the lawn trails are *thin*. It
separates them with a morphological opening (7×7) that removes thin structures.
On **burrowing / dark-field** footage the worm itself is often thin and there is
no lawn, so that opening **erased the worm** — every frame came back with no
spine and had to be re-spined by hand, even when the segmentation mask looked
perfect.

**Fix.** When you provide a **reviewed** segmentation (via the `g` workbench),
the tracker now trusts it:

- the aggressive thick-worm opening is replaced by a gentle one, and
- if the worm is too thin to survive even that, it falls back to the reviewed
  mask itself.

So a good segmentation now produces spines directly instead of flagging most
frames for manual fixing.

**Scope.** This only changes the *reviewed-segmentation* path (what you use after
pressing `g`). The default unreviewed crawling-on-lawn detector is unchanged, so
existing crawling analyses behave exactly as before.

> Note: this is a segmentation/geometry change I could not run against your
> footage here — please confirm on your burrowing movie that frames now show
> spines. If some frames still flag, tell me and I'll look at the next filter
> (worm-area identity bounds) for burrowing posture changes.
