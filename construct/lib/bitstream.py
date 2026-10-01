from io import BlockingIOError
from time import sleep
from sys import maxsize


class RestreamedBytesIO(object):

    def __init__(self, substream, decoder, decoderunit, encoder, encoderunit):
        self.substream = substream
        self.encoder = encoder
        self.encoderunit = encoderunit
        self.decoder = decoder
        self.decoderunit = decoderunit
        self.rbuffer = b""
        self.wbuffer = b""
        self.sincereadwritten = 0

    def read(self, count=None):
        if count is None:
            while True:
                data = self.substream.read(self.decoderunit)
                if data is None or len(data) == 0:
                    break
                self.rbuffer += self.decoder(data)
            data, self.rbuffer = self.rbuffer, b''
            self.sincereadwritten += len(data)
            return data

        else:
            if count < 0:
                raise ValueError("count cannot be negative")
            while len(self.rbuffer) < count:
                data = self.substream.read(self.decoderunit)
                if data is None or len(data) == 0:
                    return b''
                self.rbuffer += self.decoder(data)
            data, self.rbuffer = self.rbuffer[:count], self.rbuffer[count:]
            self.sincereadwritten += count
            return data

    def write(self, data):
        self.wbuffer += data
        datalen = len(data)
        while len(self.wbuffer) >= self.encoderunit:
            data, self.wbuffer = self.wbuffer[:self.encoderunit], self.wbuffer[self.encoderunit:]
            self.substream.write(self.encoder(data))
        self.sincereadwritten += datalen
        return datalen

    def close(self):
        if len(self.rbuffer):
            raise ValueError("closing stream but %d unread bytes remain, %d is decoded unit" % (len(self.rbuffer), self.decoderunit))
        if len(self.wbuffer):
            raise ValueError("closing stream but %d unwritten bytes remain, %d is encoded unit" % (len(self.wbuffer), self.encoderunit))

    def seek(self, at, whence=0):
        if whence == 0 and at == self.sincereadwritten:
            pass
        else:
            raise IOError

    def seekable(self):
        return False

    def tell(self):
        """WARNING: tell is correct only on read-only and write-only instances."""
        return self.sincereadwritten

    def tellable(self):
        return True


class SeekableRestreamedBytesIO(object):
    r"""
    Seekable variant of :class:`RestreamedBytesIO` for fixed-ratio conversions.

    Works only on top of seekable substreams, and only with decoder/encoder
    pairs that convert a fixed number of units (like bytes2bits/bits2bytes
    used by Bitwise/Bytewise). Positions (seek/tell) are expressed in decoded
    units, eg. bits when used by Bitwise, and are relative to the substream
    position at construction time. Variable-length codecs (like zlib) are
    not supported and rejected with ValueError at construction.

    Closing the stream requires the current position to be aligned to whole
    decoded units (eg. whole bytes in a Bitwise context), and positions the
    substream right after the consumed units. Partially written units are
    merged with existing substream content, or rejected if there is none,
    so no padding bits are silently invented.

    Like RestreamedBytesIO, an instance is either read-only or write-only.
    """

    MAXCACHEDBLOCKS = 1024

    def __init__(self, substream, decoder, decoderunit, encoder, encoderunit):
        seekable = getattr(substream, "seekable", None)
        if seekable is not None and not seekable():
            raise ValueError("substream is not seekable")
        try:
            base = substream.tell()
            substream.seek(base)
        except Exception:
            raise ValueError("substream does not support seek/tell")
        try:
            ratio = len(decoder(bytes(decoderunit)))
            consistent = ratio >= 1 and encoderunit == ratio and len(encoder(bytes(encoderunit))) == decoderunit
        except Exception:
            consistent = False
        if not consistent:
            raise ValueError("decoder/encoder pair is not a fixed-ratio conversion")
        self.substream = substream
        self.decoder = decoder
        self.decoderunit = decoderunit
        self.encoder = encoder
        self.encoderunit = encoderunit
        self.ratio = ratio
        self.base = base
        self.pos = 0
        self.wend = 0
        # pending written units, block index -> [bytearray of ratio units, set of valid indices]
        self.wcache = {}

    def read(self, count=None):
        if count is not None and count < 0:
            raise ValueError("count cannot be negative")
        startblock, offset = divmod(self.pos, self.ratio)
        self.substream.seek(self.base + startblock * self.decoderunit)
        if count is None:
            chunks = []
            while True:
                data = self.substream.read(1024 * self.decoderunit)
                if not data:
                    break
                chunks.append(data)
                if len(data) % self.decoderunit:
                    break
            data = b"".join(chunks)
        else:
            blocksneeded = (offset + count + self.ratio - 1) // self.ratio
            data = self.substream.read(blocksneeded * self.decoderunit)
        fullunits = len(data) // self.decoderunit
        decoded = bytearray(self.decoder(data[:fullunits * self.decoderunit]))
        if self.wcache:
            for index in range(startblock, startblock + fullunits):
                entry = self.wcache.get(index)
                if entry is not None:
                    block, valid = entry
                    at = (index - startblock) * self.ratio
                    for i in valid:
                        decoded[at + i] = block[i]
        if count is None:
            result = bytes(decoded[offset:])
        else:
            result = bytes(decoded[offset:offset + count])
        self.pos += len(result)
        return result

    def write(self, data):
        datalen = len(data)
        pos = self.pos
        i = 0
        while i < datalen:
            index, offset = divmod(pos + i, self.ratio)
            take = min(datalen - i, self.ratio - offset)
            chunk = data[i:i + take]
            if offset == 0 and take == self.ratio and index not in self.wcache:
                self.substream.seek(self.base + index * self.decoderunit)
                self.substream.write(self.encoder(chunk))
            else:
                entry = self.wcache.get(index)
                if entry is None:
                    entry = self.wcache[index] = [bytearray(self.ratio), set()]
                entry[0][offset:offset + take] = chunk
                entry[1].update(range(offset, offset + take))
                if len(entry[1]) == self.ratio:
                    self._flushcomplete(index)
            i += take
        while len(self.wcache) > self.MAXCACHEDBLOCKS:
            self._flushpartial(min(self.wcache))
        self.pos += datalen
        self.wend = max(self.wend, self.pos)
        return datalen

    def _flushcomplete(self, index):
        block, valid = self.wcache.pop(index)
        self.substream.seek(self.base + index * self.decoderunit)
        self.substream.write(self.encoder(bytes(block)))

    def _flushpartial(self, index):
        block, valid = self.wcache.pop(index)
        self.substream.seek(self.base + index * self.decoderunit)
        existing = self.substream.read(self.decoderunit)
        if len(existing) != self.decoderunit:
            missing = self.ratio - len(valid)
            raise ValueError("cannot write partial unit, %d of %d units have no data to merge with" % (missing, self.ratio))
        merged = bytearray(self.decoder(existing))
        for i in valid:
            merged[i] = block[i]
        self.substream.seek(self.base + index * self.decoderunit)
        self.substream.write(self.encoder(bytes(merged)))

    def close(self):
        while self.wcache:
            self._flushpartial(min(self.wcache))
        if self.pos % self.ratio != 0:
            raise ValueError("closing stream at position %d which is not aligned to %d units" % (self.pos, self.ratio))
        self.substream.seek(self.base + (self.pos // self.ratio) * self.decoderunit)

    def seek(self, at, whence=0):
        if whence == 0:
            newpos = at
        elif whence == 1:
            newpos = self.pos + at
        elif whence == 2:
            fallback = self.substream.tell()
            end = self.substream.seek(0, 2)
            self.substream.seek(fallback)
            endpos = ((end - self.base) // self.decoderunit) * self.ratio
            newpos = max(endpos, self.wend) + at
        else:
            raise ValueError("invalid whence value")
        if newpos < 0:
            raise ValueError("cannot seek to negative position")
        self.pos = newpos
        return newpos

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def tellable(self):
        return True
class RebufferedBytesIO(object):

    def __init__(self, substream, tailcutoff=None):
        self.substream = substream
        self.offset = 0
        self.rwbuffer = b""
        self.moved = 0
        self.tailcutoff = tailcutoff

    def read(self, count=None):
        if count is None:
            raise ValueError("count must be integer, reading until EOF not supported")
        startsat = self.offset
        endsat = startsat + count
        if startsat < self.moved:
            raise IOError("could not read because tail was cut off")
        while self.moved + len(self.rwbuffer) < endsat:
            try:
                newdata = self.substream.read(128*1024)
            except BlockingIOError:
                newdata = None
            if not newdata:
                sleep(0)
                continue
            self.rwbuffer += newdata
        data = self.rwbuffer[startsat-self.moved:endsat-self.moved]
        self.offset += count
        if self.tailcutoff is not None and self.moved < self.offset - self.tailcutoff:
            removed = self.offset - self.tailcutoff - self.moved
            self.moved += removed
            self.rwbuffer = self.rwbuffer[removed:]
        if len(data) < count:
            raise IOError("could not read enough bytes, something went wrong")
        return data

    def write(self, data):
        startsat = self.offset
        endsat = startsat + len(data)
        while self.moved + len(self.rwbuffer) < startsat:
            newdata = self.substream.read(128*1024)
            self.rwbuffer += newdata
            if not newdata:
                sleep(0)
        self.rwbuffer = self.rwbuffer[:startsat-self.moved] + data + self.rwbuffer[endsat-self.moved:]
        self.offset = endsat
        if self.tailcutoff is not None and self.moved < self.offset - self.tailcutoff:
            removed = self.offset - self.tailcutoff - self.moved
            self.moved += removed
            self.rwbuffer = self.rwbuffer[removed:]
        return len(data)

    def seek(self, at, whence=0):
        if whence == 0:
            self.offset = at
            return self.offset
        elif whence == 1:
            self.offset += at
            return self.offset
        else:
            raise ValueError("this class seeks only with whence: 0 and 1 (excluded 2)")

    def seekable(self):
        return True

    def tell(self):
        return self.offset

    def tellable(self):
        return True

    def cachedfrom(self):
        return self.moved

    def cachedto(self):
        return self.moved + len(self.rwbuffer)
