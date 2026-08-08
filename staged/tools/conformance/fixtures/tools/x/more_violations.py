"""The two rules the first fixture set did not exercise."""


def rate_note():
    # 30 fps established for these rigs, so pumping is countable.
    return 30.0


def measure_cells(image, mask):
    return image[mask].sum()
