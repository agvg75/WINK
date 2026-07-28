# NIKE Lab Tools v11.69 (hotfix)

## Fix: Track one worm hung after choosing a file

- In v11.68 the new consolidated setup form was made **transient to the hidden
  launcher window**. On Windows that can leave the form **invisible**, so after
  you picked a file the tool appeared to do nothing (it was waiting on a dialog
  you could not see).
- The form now follows the standard tkinter dialog pattern used by
  `simpledialog`: it only becomes transient when the parent window is actually
  viewable, then explicitly shows itself and takes the modal grab. The setup
  form appears normally again.

Nothing else from v11.68 changed (dropdown setup, scrollable/skippable
focus/exclude ROIs, screen-clamped windows).
