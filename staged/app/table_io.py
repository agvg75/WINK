"""Reading result tables safely under pandas 3.

WHY THIS EXISTS. pandas 3 changed how a column holding a stray non-numeric cell
is read. Under pandas 2 it came back as `object`; under pandas 3 it comes back
as StringDtype. numpy refuses both:

    TypeError: ufunc 'isfinite' not supported for the input types, and the
    inputs could not be safely coerced to any supported types

so ONE bad cell anywhere in a measurement column now aborts an entire analysis,
with a message naming numpy internals rather than the column at fault. Reported
from the population tracking tool, 2026-08-04, immediately after the environment
was rebuilt with pandas 3.0.x. Every module that reads a result CSV and then
does arithmetic on it is exposed; there are about twenty.

THE TRAP IN FIXING IT. The obvious fix - coerce columns whose NAMES look like
measurements - is worse than the bug. Patterns like "_s" and "_x" also match
`fps_source`, `um_per_px_source` and `spine_x_json`, which are genuine text
columns recording whether a frame rate was declared or guessed. Coercing those
turns "declared" into NaN and destroys the provenance silently. The first
version of this did exactly that.

So the decision is made from the DATA. Measured across the lab's own result
CSVs, text provenance columns parse as numbers 0% of the time while measurement
columns parse 75-100% of the time even when carrying sentinels. The threshold
sits at 0.6 rather than 0.5 so that a column which is exactly half numbers and
half words - maximally ambiguous, and the one case where converting would
destroy half the content - falls on the "leave it alone" side.
"""
from __future__ import annotations


def coerce_numeric(df, columns=None, min_numeric_fraction=0.6):
    """Convert columns that are numeric in substance but not in dtype.

    A column is converted only when most of its non-empty values already parse
    as numbers. Genuine text columns are left exactly as they are, values
    included. Values that cannot be numbers become NaN - which is what they
    always meant, and which every downstream calculation already handles,
    because these columns are full of NaN by design.
    """
    import pandas as pd

    if columns is None:
        columns = list(df.columns)
    converted = []
    for c in columns:
        if c not in df.columns:
            continue
        s = df[c]
        if s.dtype.kind in "fiub":
            continue
        present = s.notna()
        if not present.any():
            continue
        coerced = pd.to_numeric(s, errors="coerce")
        if float(coerced[present].notna().mean()) >= min_numeric_fraction:
            df[c] = coerced
            converted.append(str(c))
    if converted:
        df.attrs["coerced_numeric_columns"] = converted
    return df


def read_table(path, coerce=True, **kwargs):
    """pandas.read_csv, with the pandas-3 dtype trap handled.

    Use this instead of pd.read_csv for any table that will be measured. The
    names of any columns that had to be converted are recorded in
    `df.attrs["coerced_numeric_columns"]`, so a run that silently rescued a
    malformed file can still say it did.
    """
    import pandas as pd

    df = pd.read_csv(path, **kwargs)
    return coerce_numeric(df) if coerce else df
