# NIKE Lab Tools v11.78

## Population basal slowing — review keys no longer jump the view

The track-review window binds `r`, `c`, and the arrow keys, which Matplotlib also
binds by default (`r` = reset view, `c` = back, arrows = back/forward). Left in
place, those pressed the reviewer's action **and** panned/zoomed/reset the image
underneath it.

Those clashing default key bindings are now cleared for this tool (the same fix
already in Track one worm), so the keys do only what the reviewer intends.

_Propagated from the Track one worm keymap fix during the cross-module audit._
