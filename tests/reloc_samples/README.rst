Relocation samples
==================

Binary samples for ``Section`` and ``OffsetField`` (see ``construct.core``).
Formats and expected objects live in ``formats.py``. Regenerate the ``.bin``
files from the repository root with::

    python -m tests.reloc_samples.generate

Samples:

- ``nested_sections.bin`` -- nested sections (a section inside a section) with
  alignment padding, referenced by absolute and relative offset fields.
- ``forward_refs.bin`` -- a table-of-contents header with forward references,
  two offset fields pointing at the same section, one relative offset.
- ``varint_growth.bin`` -- VarInt offset fields whose encoded length grows
  from 1 to 2 bytes once the section offset crosses 127, forcing the build
  layout to converge over multiple passes.
