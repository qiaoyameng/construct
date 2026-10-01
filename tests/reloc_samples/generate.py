# -*- coding: utf-8 -*-
# Regenerates the .bin sample files in this directory.
# Run from the repository root: python -m tests.reloc_samples.generate

import os

from tests.reloc_samples.formats import SAMPLES


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    for filename, fmt, obj in SAMPLES:
        data = fmt.build(obj)
        with open(os.path.join(here, filename), "wb") as f:
            f.write(data)
        print("%s: %d bytes" % (filename, len(data)))


if __name__ == "__main__":
    main()
