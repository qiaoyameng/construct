===================
Stream manipulation
===================

.. note::

    Certain constructs are available only for seekable and tellable streams (in-memory and files). Sockets and pipes do not support neither, so you'll have to first read the data from the stream and parse it in-memory, or use experimental ``Rebuffered`` wrapper.


Field wrappers
==============

``Pointer`` allows for non-sequential construction. The pointer first moves the stream into new position, does the construction, and then restores the stream back to original position. This allows for random access within the stream.

>>> d = Pointer(8, Bytes(1))
>>> d.parse(b"abcdefghijkl")
b'i'
>>> d.build(b"Z")
b'\x00\x00\x00\x00\x00\x00\x00\x00Z'

``Peek`` parses a field but restores the stream position afterwards (it peeks into the stream). Building does nothing, it does NOT defer to subcon.

>>> d = Sequence(Peek(Int16ul), Peek(Int16ub))
>>> d.parse(b"\x01\x02")
ListContainer([513, 258])
>>> d.sizeof()
0

``Prefixed`` normally reads the entire declared segment into memory and parses the subcon over a new ``BytesIO``. Pass ``streaming=True`` to instead parse over a bounded window of the parent stream. The subcon sees its own origin (position 0) and EOF (the declared length); no read or seek crosses either boundary. This keeps memory bounded by the subcon's individual read sizes instead of the segment length.

>>> d = Struct(
...     "body" / Prefixed(Int32ub, GreedyRange(Int32ul), streaming=True),
...     "tail" / Byte,
... )

On a seekable stream, parsing always leaves the stream exactly at the end of the segment: when the subcon stops early, raises, or is referenced lazily (``Lazy``), the position is pinned to ``lenfield_start + length``. A following field is therefore always aligned.

On a non-seekable stream only forward parsing is supported: the window consumes remaining bytes by reading and discarding them, so the next field still starts aligned; backwards seeks (as used by ``Peek`` or ``Lazy`` evaluation) raise ``StreamError``.

``OffsettedEnd`` parses a greedy subcon until EOF plus a negative offset. This way you can read (almost) all data but leave some bytes left for a fixed sized footer.

>>> d = Struct(
...     "header" / Bytes(2),
...     "data" / OffsettedEnd(-2, GreedyBytes),
...     "footer" / Bytes(2),
... )
>>> d.parse(b"\x01\x02\x03\x04\x05\x06\x07")
Container(header=b'\x01\x02', data=b'\x03\x04\x05', footer=b'\x06\x07')


Pure side effects
=================

``Seek`` makes a jump within the stream and leaves it there, for other constructs to follow up from that location. It does not read or write anything to the stream by itself.

>>> d = Sequence(Bytes(10), Seek(5), Byte)
>>> d.build([b"0123456789", None, 255])
b'01234\xff6789'

``Tell`` checks the current stream position and returns it. The returned value gets automatically inserted into the context dictionary. It also does not read or write anything to the stream by itself.

>>> d = Struct("num"/VarInt, "offset"/Tell)
>>> d.parse(b"X")
Container(num=88, offset=1)
>>> d.build(dict(num=88))
b'X'


Other fields
=================

``Pass`` literally does nothing. It is mostly used internally by ``If(IfThenElse)`` and ``Padding(Padded)``.

>>> Pass.parse(b"")
None
>>> Pass.build(None)
b''
>>> Pass.sizeof()
0

``Terminated`` only works during parsing. It checks if the stream reached EOF and raises error if not.

>>> Terminated.parse(b"")
None
>>> Terminated.parse(b"remaining")
TerminatedError: Error in path (parsing)
expected end of stream
